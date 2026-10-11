import pytest

from core.permission_manager import BoodaPermissionManager
from core.permission_policy import BoodaPermissionPolicy
from core.brain import BoodaAgent
from core.agent_session import BoodaAgentSessionStore
from core.audit_log import BoodaAuditLog
from core.memory import BoodaStructuredMemoryStore, JsonlBoodaMemory
from core.executor import BoodaExecutor
from core.planning import BoodaGoal, BoodaPlan, PlanStep
from core.task_manager import BoodaTaskManager
from core.tool_registry import BoodaToolRegistry


class Planner:
    def __init__(self, plan):
        self.plan = plan
        self.calls = []

    def create_plan(self, goal, memory):
        self.calls.append((goal, memory))
        return self.plan


class Memory:
    def __init__(self):
        self.entries = []

    def recall(self, goal_id):
        return {"goal_id": goal_id}

    def remember(self, goal_id, entry):
        self.entries.append((goal_id, entry))


class Verifier:
    def __init__(self, accepted=True):
        self.accepted = accepted
        self.calls = []

    def verify(self, task, result, goal):
        self.calls.append((task, result, goal))
        return self.accepted


def allowed_permissions(*names):
    permissions = BoodaPermissionManager()
    for name in names:
        permissions.add_permission(name, allowed=True)
    return permissions


def make_agent(
    plan,
    *,
    verifier=None,
    memory=None,
    registry=None,
    executor=None,
    permission_manager=None,
):
    return BoodaAgent(
        Planner(plan), BoodaTaskManager(), registry or BoodaToolRegistry(),
        executor or BoodaExecutor(), verifier=verifier, memory=memory,
        permission_manager=permission_manager,
        permission_policy=(
            BoodaPermissionPolicy() if permission_manager is not None else None
        ),
    )


def test_goal_intake_and_planning_record_context_and_memory_hooks():
    goal = BoodaGoal("goal-1", "Increase client sales", {"client": "Sengary"})
    plan = BoodaPlan("goal-1", (PlanStep("research", "Research", capability="research"),))
    memory, agent = Memory(), make_agent(plan, memory=Memory())
    agent.memory = memory

    agent.intake(goal)
    agent.plan()

    assert agent.state.goal == goal
    assert agent.state.phase == "ready"
    assert agent.task_manager.get_task("research").status == "pending"
    assert memory.entries[0][1]["event"] == "goal_received"
    assert memory.entries[1][1]["event"] == "plan_created"


def test_dependencies_gate_execution_and_verification_completes_goal():
    plan = BoodaPlan("g", (
        PlanStep("research", "Research", capability="research", permission_name="research"),
        PlanStep("campaign", "Build campaign", capability="campaign", permission_name="campaign", depends_on=("research",)),
    ))
    registry = BoodaToolRegistry()
    registry.register("research", lambda task: "insights")
    registry.register("campaign", lambda task: "campaign draft")
    verifier = Verifier()
    agent = make_agent(
        plan,
        verifier=verifier,
        registry=registry,
        permission_manager=allowed_permissions("research", "campaign"),
    )
    agent.intake(BoodaGoal("g", "Launch a campaign"))
    agent.plan()

    first = agent.run_once()
    assert first.task_id == "research" and first.status == "completed"
    assert agent.task_manager.get_task("campaign").status == "pending"
    second = agent.run_once()

    assert second.task_id == "campaign" and second.status == "completed"
    assert agent.state.phase == "completed"
    assert len(verifier.calls) == 2


def test_run_until_blocked_advances_ready_work_in_dependency_order():
    plan = BoodaPlan("g", (
        PlanStep("research", "Research", capability="research", permission_name="research"),
        PlanStep("campaign", "Build campaign", capability="campaign", permission_name="campaign", depends_on=("research",)),
    ))
    registry = BoodaToolRegistry()
    registry.register("research", lambda task: "insights")
    registry.register("campaign", lambda task: "draft")
    agent = make_agent(
        plan,
        registry=registry,
        permission_manager=allowed_permissions("research", "campaign"),
    )
    agent.intake(BoodaGoal("g", "Launch campaign"))
    agent.plan()

    outcomes = agent.run_until_blocked()

    assert [outcome.task_id for outcome in outcomes] == ["research", "campaign"]
    assert agent.state.phase == "completed"


def test_failed_verification_blocks_downstream_tasks():
    plan = BoodaPlan("g", (
        PlanStep("draft", "Draft", capability="draft", permission_name="draft"),
        PlanStep("publish", "Publish", capability="publish", permission_name="publish", depends_on=("draft",)),
    ))
    registry = BoodaToolRegistry()
    registry.register("draft", lambda task: "bad draft")
    registry.register("publish", lambda task: "published")
    agent = make_agent(
        plan,
        registry=registry,
        verifier=Verifier(accepted=False),
        permission_manager=allowed_permissions("draft", "publish"),
    )
    agent.intake(BoodaGoal("g", "Prepare campaign"))
    agent.plan()

    assert agent.run_once().status == "failed"
    blocked = agent.run_once()
    assert blocked.status == "blocked"
    assert agent.state.phase == "needs_attention"
    assert registry.get("publish") is not None


def test_missing_capability_returns_control_to_caller_without_execution():
    plan = BoodaPlan("g", (PlanStep("video", "Create video", capability="video.generate"),))
    agent = make_agent(plan)
    agent.intake(BoodaGoal("g", "Create a video"))
    agent.plan()

    outcome = agent.run_once()

    assert outcome["status"] == "waiting_for_capability"
    assert outcome["task"].status == "pending"
    assert agent.state.phase == "waiting_for_capability"


def test_plan_rejects_cycles_and_unknown_dependencies():
    with pytest.raises(ValueError, match="Unknown dependencies"):
        BoodaPlan("g", (PlanStep("a", "A", depends_on=("missing",)),))
    with pytest.raises(ValueError, match="cycles"):
        BoodaPlan("g", (
            PlanStep("a", "A", depends_on=("b",)),
            PlanStep("b", "B", depends_on=("a",)),
        ))


def test_plan_collision_does_not_add_partial_tasks_and_can_retry():
    manager = BoodaTaskManager()
    manager.add_task("taken", "Existing")
    planner = Planner(BoodaPlan("g", (
        PlanStep("new", "New"),
        PlanStep("taken", "Collision"),
    )))
    agent = BoodaAgent(planner, manager, BoodaToolRegistry(), BoodaExecutor())
    agent.intake(BoodaGoal("g", "Try planning"))

    with pytest.raises(ValueError, match="Task already exists: taken"):
        agent.plan()

    assert manager.get_task("new") is None
    assert agent.state.phase == "received"
    planner.plan = BoodaPlan("g", (PlanStep("new", "New"),))
    assert agent.plan().steps[0].task_id == "new"


def test_unfinished_goal_requires_explicit_replacement():
    first_plan = BoodaPlan("first", (PlanStep("first-task", "First"),))
    agent = make_agent(first_plan)
    agent.intake(BoodaGoal("first", "First goal"))
    agent.plan()

    with pytest.raises(RuntimeError, match="unfinished"):
        agent.intake(BoodaGoal("second", "Second goal"))
    agent.intake(BoodaGoal("second", "Second goal"), replace_current=True)

    assert agent._steps == {}


def test_agent_restores_plan_and_continues_after_restart(tmp_path):
    task_path = tmp_path / "tasks.json"
    session_store = BoodaAgentSessionStore(tmp_path / "sessions.json")
    plan = BoodaPlan("g", (
        PlanStep("do-work", "Do work", capability="work", permission_name="work"),
    ))
    registry = BoodaToolRegistry()
    registry.register("work", lambda _task: "done")
    first = BoodaAgent(
        Planner(plan), BoodaTaskManager(task_path), registry, BoodaExecutor(),
        permission_manager=allowed_permissions("work"),
        permission_policy=BoodaPermissionPolicy(),
        session_store=session_store,
    )
    first.intake(BoodaGoal("g", "Finish work"))
    first.plan()

    restored = BoodaAgent(
        Planner(plan), BoodaTaskManager(task_path), registry, BoodaExecutor(),
        permission_manager=allowed_permissions("work"),
        permission_policy=BoodaPermissionPolicy(),
        session_store=session_store,
    )
    assert restored.state.goal.goal_id == "g"
    assert restored.state.plan.plan_id == "plan-1"
    assert restored.run_once().status == "completed"


def test_interrupted_action_requires_explicit_retry_after_restart(tmp_path):
    task_path = tmp_path / "tasks.json"
    session_store = BoodaAgentSessionStore(tmp_path / "sessions.json")
    plan = BoodaPlan("g", (
        PlanStep("maybe-done", "May have run", capability="work", permission_name="work"),
    ))
    registry = BoodaToolRegistry()
    registry.register("work", lambda _task: "done")
    first = BoodaAgent(
        Planner(plan), BoodaTaskManager(task_path), registry, BoodaExecutor(),
        permission_manager=allowed_permissions("work"),
        permission_policy=BoodaPermissionPolicy(),
        session_store=session_store,
    )
    first.intake(BoodaGoal("g", "Recover carefully"))
    first.plan()
    task = first.task_manager.get_task("maybe-done")
    task.start()
    first.state.phase = "running"
    first.state.set_task(task)
    first._persist_state()

    restored = BoodaAgent(
        Planner(plan), BoodaTaskManager(task_path), registry, BoodaExecutor(),
        permission_manager=allowed_permissions("work"),
        permission_policy=BoodaPermissionPolicy(),
        session_store=session_store,
    )
    assert restored.state.phase == "needs_attention"
    assert restored.state.interrupted_task_id == "maybe-done"
    with pytest.raises(ValueError, match="explicit retry"):
        restored.retry_interrupted_task("wrong-task")
    restored.retry_interrupted_task("maybe-done")
    assert restored.run_once().status == "completed"


def test_agent_uses_conversational_planner_without_persisting_chat_content(tmp_path):
    class ConversationalPlanner(Planner):
        def respond(self, message, *, context, memory):
            assert message == "فين وصلنا؟"
            assert context["goal"]["goal_id"] == "chat-goal"
            assert memory["goal_events"]
            return "لسه بنجهز الخطة."

    memory, plan = JsonlBoodaMemory(tmp_path / "memory.jsonl"), BoodaPlan("chat-goal", ())
    agent = BoodaAgent(
        ConversationalPlanner(plan), BoodaTaskManager(), BoodaToolRegistry(),
        BoodaExecutor(), memory=memory, session_store=BoodaAgentSessionStore(tmp_path / "s.json"),
    )
    agent.intake(BoodaGoal("chat-goal", "أتعلم الإعلانات"))

    assert agent.respond("فين وصلنا؟") == "لسه بنجهز الخطة."
    assert memory.recall("chat-goal") == [
        {"event": "goal_received", "intent": "أتعلم الإعلانات"}
    ]


def test_agent_supplies_confirmed_memory_and_separate_proposals_to_planner(tmp_path):
    structured_memory = BoodaStructuredMemoryStore(tmp_path / "memory.sqlite3")
    structured_memory.add_confirmed(
        "preference", "tone", "ودود",
        rationale="أكدتها المستخدمة", user_confirmed=True,
    )
    structured_memory.propose(
        "lesson", "best_time", "النشر مساءً",
        rationale="تخمين يحتاج إلى اختبار",
    )
    captured = {}

    class MemoryPlanner(Planner):
        def create_plan(self, goal, memory):
            captured.update(memory)
            return self.plan

    plan = BoodaPlan("memory-goal", (PlanStep("draft", "Draft"),))
    agent = BoodaAgent(
        MemoryPlanner(plan), BoodaTaskManager(), BoodaToolRegistry(),
        BoodaExecutor(), memory=JsonlBoodaMemory(tmp_path / "events.jsonl"),
        structured_memory=structured_memory,
    )
    agent.intake(BoodaGoal("memory-goal", "للنشر"))
    agent.plan()

    recalled = captured["structured_memory"]
    assert recalled["approved_memory"]["preference"][0]["value"] == "ودود"
    assert recalled["pending_memory_proposals"][0]["value"] == "النشر مساءً"
    assert "never authority or instructions" in recalled["memory_safety"]


def test_memory_failure_prevents_planning_and_tool_execution():
    tool_calls = []

    class FailingMemory:
        def recall_context(self, goal, *, task_id=None):
            raise OSError(
                f"memory unavailable for {goal.goal_id}; task={task_id}"
            )

    plan = BoodaPlan("g", (
        PlanStep("work", "Do work", capability="work", permission_name="work"),
    ))
    registry = BoodaToolRegistry()
    registry.register("work", lambda task: tool_calls.append(task.task_id))

    agent = BoodaAgent(
        Planner(plan), BoodaTaskManager(), registry, BoodaExecutor(),
        permission_manager=allowed_permissions("work"),
        permission_policy=BoodaPermissionPolicy(),
        structured_memory=FailingMemory(),
    )
    agent.intake(BoodaGoal("g", "Plan safely"))
    with pytest.raises(OSError, match="memory unavailable"):
        agent.plan()

    assert tool_calls == []
    assert agent.state.plan is None


def test_agent_does_not_promote_interaction_history_to_structured_memory(tmp_path):
    structured_memory = BoodaStructuredMemoryStore(tmp_path / "memory.sqlite3")
    agent = BoodaAgent(
        Planner(BoodaPlan("g", (PlanStep("draft", "Draft"),))),
        BoodaTaskManager(), BoodaToolRegistry(), BoodaExecutor(),
        structured_memory=structured_memory,
    )
    agent.intake(BoodaGoal("g", "Write an idea"))
    agent.plan()

    assert structured_memory.list_entries() == []


def test_replan_is_review_gated_and_does_not_repeat_failed_step():
    initial = BoodaPlan("g", (
        PlanStep("broken", "Broken action", capability="broken", permission_name="broken"),
    ))
    planner = Planner(initial)
    registry = BoodaToolRegistry()
    registry.register("broken", lambda _task: (_ for _ in ()).throw(RuntimeError("failed")))
    registry.register("fixed", lambda _task: "recovered")
    agent = BoodaAgent(
        planner, BoodaTaskManager(), registry, BoodaExecutor(),
        permission_manager=allowed_permissions("broken", "fixed"),
        permission_policy=BoodaPermissionPolicy(),
    )
    agent.intake(BoodaGoal("g", "Complete safely"))
    agent.plan()
    assert agent.run_once().status == "uncertain"

    planner.plan = BoodaPlan("g", (
        PlanStep("retry", "Corrective action", capability="fixed", permission_name="fixed"),
    ))
    revised = agent.replan(
        "The first action outcome is uncertain; use the alternate method"
    )
    assert revised.steps[0].task_id == "g-revision-1-1"
    with pytest.raises(RuntimeError, match="approve"):
        agent.run_once()

    agent.approve_replan(revised.plan_id)
    assert agent.run_once().result == "recovered"


def test_session_restore_repairs_only_missing_pending_plan_tasks(tmp_path):
    task_path = tmp_path / "tasks.json"
    session_store = BoodaAgentSessionStore(tmp_path / "sessions.json")
    plan = BoodaPlan("g", (PlanStep("step-1", "Study"),))
    first = BoodaAgent(
        Planner(plan), BoodaTaskManager(task_path), BoodaToolRegistry(), BoodaExecutor(),
        session_store=session_store,
    )
    first.intake(BoodaGoal("g", "Learn"))
    first.plan()
    first.task_manager.remove_task("step-1")

    restored = BoodaAgent(
        Planner(plan), BoodaTaskManager(task_path), BoodaToolRegistry(), BoodaExecutor(),
        session_store=session_store,
    )

    assert restored.state.phase == "ready"
    assert restored.task_manager.get_task("step-1").status == "pending"


def test_replan_rejects_repeating_completed_work():
    plan = BoodaPlan("g", (
        PlanStep("finished", "Already done", capability="work", permission_name="work"),
        PlanStep("broken", "Broken", capability="broken", permission_name="broken"),
    ))
    planner = Planner(plan)
    registry = BoodaToolRegistry()
    registry.register("work", lambda _task: "done")
    registry.register("broken", lambda _task: (_ for _ in ()).throw(RuntimeError("failed")))
    agent = BoodaAgent(
        planner, BoodaTaskManager(), registry, BoodaExecutor(),
        permission_manager=allowed_permissions("work", "broken"),
        permission_policy=BoodaPermissionPolicy(),
    )
    agent.intake(BoodaGoal("g", "Finish tasks"))
    agent.plan()
    agent.run_once()
    assert agent.run_once().status == "uncertain"
    planner.plan = BoodaPlan("g", (
        PlanStep("duplicate", "Already done", capability="work", permission_name="work"),
        PlanStep("repair", "Repair broken action", capability="work", permission_name="work"),
    ))

    with pytest.raises(ValueError, match="repeats completed work"):
        agent.replan("Repair remaining work")


def test_uncertain_task_blocks_dependents_and_is_not_retried_automatically():
    plan = BoodaPlan("g", (
        PlanStep(
            "uncertain-step",
            "Possibly sent",
            capability="uncertain",
            permission_name="uncertain",
        ),
        PlanStep(
            "dependent-step",
            "Follow-up",
            capability="follow-up",
            permission_name="follow-up",
            depends_on=("uncertain-step",),
        ),
    ))
    planner = Planner(plan)
    registry = BoodaToolRegistry()
    calls = []

    def uncertain_action(_task):
        calls.append("uncertain")
        raise RuntimeError("Remote result unavailable.")

    registry.register("uncertain", uncertain_action)
    registry.register(
        "follow-up",
        lambda _task: calls.append("follow-up") or "done",
    )
    agent = BoodaAgent(
        planner,
        BoodaTaskManager(),
        registry,
        BoodaExecutor(),
        permission_manager=allowed_permissions("uncertain", "follow-up"),
        permission_policy=BoodaPermissionPolicy(),
    )
    agent.intake(BoodaGoal("g", "Complete dependent work"))
    agent.plan()

    first = agent.run_once()
    second = agent.run_once()

    assert first.status == "uncertain"
    assert second.status == "blocked"
    assert calls == ["uncertain"]
    assert agent.state.phase == "needs_attention"


def test_concurrent_run_request_does_not_start_second_task():
    plan = BoodaPlan("g", (PlanStep("work", "Work", capability="work"),))
    registry = BoodaToolRegistry()
    calls = []
    registry.register("work", lambda _task: calls.append("ran") or "done")
    agent = BoodaAgent(Planner(plan), BoodaTaskManager(), registry, BoodaExecutor())
    agent.intake(BoodaGoal("g", "Do work"))
    agent.plan()
    current_task = BoodaTaskManager().add_task("other", "Other")
    agent.state.set_task(current_task)

    result = agent.run_once()

    assert result["status"] == "agent_busy"
    assert calls == []


def test_explicit_provider_plan_requires_review_before_execution(tmp_path):
    class ReviewRequiredPlanner(Planner):
        requires_explicit_permissions = True

        def configure_agent(self, *, registry, permission_manager):
            self.configured = True

    calls = []
    audit_log = BoodaAuditLog(tmp_path / "audit.jsonl")
    registry = BoodaToolRegistry()
    registry.register("save", lambda task: calls.append(task.task_id) or "saved")
    permissions = BoodaPermissionManager()
    permissions.add_permission("save", allowed=True)
    agent = BoodaAgent(
        ReviewRequiredPlanner(
            BoodaPlan("review-goal", (
                PlanStep(
                    "review-task", "Save reviewed draft",
                    capability="save", permission_name="save",
                ),
            ))
        ),
        BoodaTaskManager(),
        registry,
        BoodaExecutor(),
        permission_manager=permissions,
        permission_policy=BoodaPermissionPolicy(),
        audit_log=audit_log,
        requested_by="owner",
    )
    agent.intake(BoodaGoal("review-goal", "Save a reviewed draft"))
    plan = agent.plan()

    assert agent.state.phase == "review_required"
    with pytest.raises(RuntimeError, match="Review and approve the plan"):
        agent.run_once()
    assert calls == []
    assert agent.task_manager.get_task("review-task").status == "pending"

    agent.approve_plan(plan.plan_id)
    assert agent.run_once().status == "completed"
    assert calls == ["review-task"]
    assert any(item["event"] == "plan_approved" for item in agent.state.history)
    audit_event = audit_log.get_events()[0]
    assert audit_event.action == "plan_approved"
    assert audit_event.requested_by == "owner"
    assert audit_event.outcome == "completed"


def test_unreviewed_plan_remains_gated_after_session_restore(tmp_path):
    plan = BoodaPlan("saved-review-goal", (
        PlanStep(
            "saved-review-task", "Save reviewed draft",
            capability="save", permission_name="save",
        ),
    ))
    session_store = BoodaAgentSessionStore(tmp_path / "sessions.json")
    registry = BoodaToolRegistry()
    calls = []
    registry.register("save", lambda task: calls.append(task.task_id) or "saved")

    class ReviewRequiredPlanner(Planner):
        requires_explicit_permissions = True

        def configure_agent(self, *, registry, permission_manager):
            self.configured = True

    permissions = BoodaPermissionManager()
    permissions.add_permission("save", allowed=True)
    first = BoodaAgent(
        ReviewRequiredPlanner(plan),
        BoodaTaskManager(tmp_path / "tasks.json"),
        registry,
        BoodaExecutor(),
        permission_manager=permissions,
        permission_policy=BoodaPermissionPolicy(),
        session_store=session_store,
        session_id="review-session",
    )
    first.intake(BoodaGoal("saved-review-goal", "Save a reviewed draft"))
    first.plan()

    restored = BoodaAgent(
        ReviewRequiredPlanner(plan),
        BoodaTaskManager(tmp_path / "tasks.json"),
        registry,
        BoodaExecutor(),
        permission_manager=permissions,
        permission_policy=BoodaPermissionPolicy(),
        session_store=session_store,
        session_id="review-session",
    )

    assert restored.state.plan_reviewed is False
    assert restored.state.phase == "review_required"
    with pytest.raises(RuntimeError, match="Review and approve the plan"):
        restored.run_once()
    assert calls == []


def test_existing_task_dependency_metadata_round_trips(tmp_path):
    path = tmp_path / "tasks.json"
    manager = BoodaTaskManager(path)
    manager.add_task("a", "A", metadata={"kind": "research"})
    manager.add_task("b", "B", depends_on=("a",))

    reopened = BoodaTaskManager(path)

    assert reopened.get_task("a").metadata == {"kind": "research"}
    assert reopened.get_task("b").depends_on == ("a",)


def test_executor_guardrails_receive_task_permission_and_approval():
    from core.permission_manager import BoodaPermissionManager
    from core.permission_policy import BoodaPermissionPolicy
    from core.risk import RiskLevel

    plan = BoodaPlan("g", (PlanStep("spend", "Spend", capability="finance.spend", permission_name="spend_money"),))
    registry = BoodaToolRegistry()
    registry.register("finance.spend", lambda task: "done")
    marker = object()

    class RecordingExecutor:
        def execute(self, **kwargs):
            assert kwargs["permission_name"] == "spend_money"
            assert kwargs["approval"] is marker
            assert kwargs["permission_manager"] is permission_manager
            assert kwargs["permission_policy"] is permission_policy
            assert kwargs["audit_log"] is audit_log
            assert kwargs["requested_by"] == "owner"
            task = kwargs["task"]
            task.start()
            task.complete(kwargs["action"]())
            return task.result

    permission_manager = BoodaPermissionManager()
    permission_manager.add_permission("spend_money", risk_level=RiskLevel.HIGH, allowed=True)
    permission_policy, audit_log = BoodaPermissionPolicy(), object()
    agent = BoodaAgent(
        Planner(plan), BoodaTaskManager(), registry, RecordingExecutor(),
        permission_manager=permission_manager,
        permission_policy=permission_policy,
        approval_provider=lambda task, step: marker,
        audit_log=audit_log,
        requested_by="owner",
    )
    agent.intake(BoodaGoal("g", "Spend safely"))
    agent.plan()

    assert agent.run_once().result == "done"


def test_agent_waits_for_approval_then_resumes_through_executor():
    from core.permission_manager import BoodaPermissionManager
    from core.permission_policy import BoodaPermissionPolicy
    from core.risk import RiskLevel
    from core.approval_manager import BoodaApprovalManager

    plan = BoodaPlan("g", (
        PlanStep("purchase", "Purchase", capability="purchase", permission_name="spend_money"),
    ))
    registry = BoodaToolRegistry()
    calls = []
    registry.register("purchase", lambda task: calls.append(task.task_id) or "done")
    permissions = BoodaPermissionManager()
    permissions.add_permission("spend_money", risk_level=RiskLevel.HIGH, allowed=True)
    approvals = BoodaApprovalManager()
    agent = BoodaAgent(
        Planner(plan), BoodaTaskManager(), registry, BoodaExecutor(),
        permission_manager=permissions,
        permission_policy=BoodaPermissionPolicy(),
        approval_provider=lambda task, step: next((
            approval for approval in approvals.approvals.values()
            if approval.task_id == task.task_id
            and approval.permission_name == step.permission_name
        ), None),
    )
    agent.intake(BoodaGoal("g", "Make purchase"))
    agent.plan()

    waiting = agent.run_once()
    assert waiting["status"] == "waiting_for_approval"
    assert waiting["task"].status == "pending"
    assert calls == []

    approval_id, _ = approvals.create_approval(
        "spend_money", approved_by="owner", task_id="purchase"
    )
    approvals.approve_approval(approval_id)
    assert agent.run_once().status == "completed"
    assert calls == ["purchase"]
