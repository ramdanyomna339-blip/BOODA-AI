from datetime import datetime

import pytest

from core.approval_manager import BoodaApprovalManager
from core.audit_log import BoodaAuditLog
from core.brain import BoodaAgent
from core.capability_registry import BoodaCapabilityRegistry
from core.event_log import BoodaEventLog
from core.evolution_manager import BoodaEvolutionManager, EVOLUTION_PERMISSION
from core.executor import BoodaExecutor
from core.permission_manager import BoodaPermissionManager
from core.permission_policy import BoodaPermissionPolicy
from core.planning import BoodaGoal, BoodaPlan, PlanStep
from core.risk import RiskLevel
from core.task import BoodaTask
from core.task_manager import BoodaTaskManager
from core.tool_registry import BoodaToolRegistry
from core.versioning import BoodaVersionStore


def _system(tmp_path):
    audit = BoodaAuditLog(tmp_path / "audit.jsonl")
    events = BoodaEventLog(tmp_path / "events.jsonl")
    versions = BoodaVersionStore(tmp_path / "versions.jsonl")
    manager = BoodaEvolutionManager(
        tmp_path / "evolution.json",
        audit_log=audit,
        event_log=events,
        version_store=versions,
    )
    return manager, audit, events, versions


def _proposal(manager):
    return manager.create_proposal(
        title="Add local document search",
        problem="Tasks cannot currently search local documents.",
        proposed_solution="Evaluate a sandboxed local search capability.",
        expected_benefit="Reuse trusted local reference material.",
        risks="Incorrect or outdated document content.",
        cost="Local maintenance only; no paid service.",
    )


def _evolution_access(tmp_path, audit):
    permissions = BoodaPermissionManager(audit_log=audit)
    permissions.add_permission(
        EVOLUTION_PERMISSION,
        risk_level=RiskLevel.HIGH,
        allowed=True,
    )
    approvals = BoodaApprovalManager(
        audit_log=audit, file_path=tmp_path / "approvals.json"
    )
    return permissions, approvals


@pytest.mark.parametrize(
    ("status", "expected"),
    [("completed", "success"), ("failed", "failure")],
)
def test_task_results_create_experience_and_unknown_evaluation(
    tmp_path, status, expected
):
    manager, audit, events, _ = _system(tmp_path)
    task = BoodaTask(
        task_id=f"task-{status}",
        title="Run local task",
        description="Use only a local registered tool.",
        status=status,
        result="Completed locally." if status == "completed" else "Tool failed.",
    )

    experience = manager.record_task_result(
        task,
        goal="Complete a local task",
        inputs_summary=task.description,
        result_summary=task.result,
    )

    assert experience["task_id"] == task.task_id
    assert experience["outcome"] == expected
    assert experience["metrics"] == {}
    assert len(experience["lessons"]) == 1
    assert isinstance(datetime.fromisoformat(experience["created_at"]), datetime)
    lesson_records = [
        item for item in manager.list_records("knowledge")
        if item["metadata"].get("kind") == "experience_lesson"
    ]
    assert len(lesson_records) == 1
    assert lesson_records[0]["source"] == f"task://{task.task_id}"
    evaluations = manager.list_records("evaluations")
    assert len(evaluations) == 1
    assert evaluations[0]["experience_id"] == experience["experience_id"]
    assert all(
        evaluations[0][metric] is None
        for metric in ("quality", "reliability", "speed", "cost", "privacy")
    )
    proposals = manager.list_records("proposals")
    if expected == "failure":
        assert len(proposals) == 1
        assert proposals[0]["status"] == "proposed"
        assert task.title in proposals[0]["problem"]
    else:
        assert proposals == []
    assert len(audit.get_events(task_id=experience["experience_id"])) == 1
    assert events.get_events(entity_type="experience")

    # Replaying a terminal-task callback must not duplicate the experience.
    assert manager.record_task_result(task, goal="ignored") == experience
    assert len(manager.list_records("experiences")) == 1


def test_agent_records_success_but_not_uncertain_execution_as_failure(tmp_path):
    manager, audit, _, _ = _system(tmp_path)
    task_manager = BoodaTaskManager()
    registry = BoodaToolRegistry()
    registry.register("run_local", lambda task: "Local result")
    registry.register(
        "fail_local",
        lambda _task: (_ for _ in ()).throw(RuntimeError("Local failure")),
    )

    class Planner:
        def __init__(self, capability):
            self.capability = capability

        def create_plan(self, goal, _memory):
            return BoodaPlan(
                goal.goal_id,
                (PlanStep(
                    task_id=f"task-{goal.goal_id}",
                    title="Run task",
                    description="Task inputs and expected behavior.",
                    capability=self.capability,
                    permission_name=self.capability,
                ),),
            )

    permissions = BoodaPermissionManager()
    permissions.add_permission("run_local", allowed=True)
    permissions.add_permission("fail_local", allowed=True)
    outcomes = []
    for goal_id, capability in (
        ("success", "run_local"),
        ("uncertain", "fail_local"),
    ):
        agent = BoodaAgent(
            Planner(capability),
            task_manager,
            registry,
            BoodaExecutor(),
            permission_manager=permissions,
            permission_policy=BoodaPermissionPolicy(),
            audit_log=audit,
            evolution_manager=manager,
        )
        agent.intake(BoodaGoal(goal_id, f"Goal {goal_id}"))
        agent.plan()
        task = agent.run_once()
        outcomes.append(task.status)

    assert outcomes == ["completed", "uncertain"]
    experiences = manager.list_records("experiences")
    assert {item["outcome"] for item in experiences} == {"success"}


def test_lesson_evaluation_and_capability_gap_are_audited(tmp_path):
    manager, audit, events, _ = _system(tmp_path)
    experience = manager.record_task_result(
        BoodaTask("task-1", "Task", "Inputs", status="completed", result="Result"),
        goal="Learn from a task",
    )

    updated = manager.add_lesson(
        experience["experience_id"], "Keep validated local inputs."
    )
    evaluation = manager.add_evaluation(
        experience["experience_id"],
        quality=0.9,
        reliability=1,
        speed=2.5,
        cost=0,
        privacy=1,
        notes="Measured in an offline run.",
    )
    gap = manager.create_capability_gap(
        "local_document_search",
        "A task needs a local document lookup capability.",
        detected_from=experience["experience_id"],
        required_tools=("local_index",),
    )

    assert updated["lessons"][-1] == "Keep validated local inputs."
    assert evaluation["quality"] == 0.9
    assert evaluation["speed"] == 2.5
    assert gap["status"] == "detected"
    assert gap["detected_from"] == experience["experience_id"]
    assert gap["required_tools"] == ("local_index",)
    assert {item.action for item in audit.get_events()} >= {
        "lesson_recorded", "evaluation_recorded", "capability_gap_detected"
    }
    assert events.get_events(entity_type="capability_gap", entity_id=gap["gap_id"])


def test_invalid_evaluation_metrics_are_rejected(tmp_path):
    manager, _, _, _ = _system(tmp_path)
    task = BoodaTask(
        task_id="task-1",
        title="Task",
        status="completed",
    )
    experience = manager.record_task_result(
        task,
        goal="Goal",
    )

    with pytest.raises(ValueError, match="quality must be between"):
        manager.add_evaluation(experience["experience_id"], quality=2)
    with pytest.raises(ValueError, match="cost must be a finite"):
        manager.add_evaluation(experience["experience_id"], cost=float("inf"))


def test_agent_missing_capability_creates_audited_gap(tmp_path):
    manager, audit, _, _ = _system(tmp_path)

    class Planner:
        def create_plan(self, goal, _memory):
            return BoodaPlan(goal.goal_id, (
                PlanStep(
                    task_id="task-search",
                    title="Search local documents",
                    description="Find matching local documents.",
                    capability="local_document_search",
                ),
            ))

    agent = BoodaAgent(
        Planner(),
        BoodaTaskManager(),
        BoodaToolRegistry(),
        BoodaExecutor(),
        audit_log=audit,
        evolution_manager=manager,
    )
    agent.intake(BoodaGoal("goal-search", "Find local information"))
    agent.plan()
    outcome = agent.run_once()

    assert outcome["status"] == "waiting_for_capability"
    gaps = manager.list_records("capability_gaps")
    assert len(gaps) == 1
    assert gaps[0]["name"] == "local_document_search"
    assert gaps[0]["detected_from"] == "task-search"
    assert gaps[0]["required_tools"] == ("local_document_search",)
    assert any(event.action == "capability_gap_detected" for event in audit.get_events())


def test_proposal_requires_sandbox_and_explicit_approval_for_adoption(tmp_path):
    manager, audit, events, versions = _system(tmp_path)
    proposal = _proposal(manager)
    permissions, approvals = _evolution_access(tmp_path, audit)

    with pytest.raises(ValueError, match="must be sandbox"):
        manager.request_adoption_approval(
            proposal["proposal_id"],
            approval_manager=approvals,
            approved_by="owner",
            created_by="requester",
            reason="Request approval.",
        )
    assert manager.get_proposal(proposal["proposal_id"])["status"] == "proposed"

    sandboxed = manager.sandbox_proposal(
        proposal["proposal_id"],
        report="Validated metadata only; no code was run.",
    )
    assert sandboxed["status"] == "sandbox"
    assert "capability" not in manager.data
    assert events.get_events(
        entity_type="improvement_proposal",
        entity_id=proposal["proposal_id"],
        event_type="improvement_sandboxed",
    )[0]["details"]["code_executed"] is False

    approval_id, approval = manager.request_adoption_approval(
        proposal["proposal_id"],
        approval_manager=approvals,
        approved_by="owner",
        created_by="requester",
        reason="Approve only after offline review.",
    )
    assert manager.get_proposal(proposal["proposal_id"])["status"] == "approval"
    assert approvals.approve_approval(approval_id, approved_by="owner")
    task = manager.adopt_proposal(
        proposal["proposal_id"],
        permission_manager=permissions,
        approval=approval,
        requested_by="owner",
        reason="Adopt reviewed proposal record.",
    )

    adopted = manager.get_proposal(proposal["proposal_id"])
    assert task.status == "completed"
    assert adopted["status"] == "adopted"
    assert adopted["approval_status"] == "approved"
    assert manager.list_records("change_log")[-1]["approval_status"] == "approved"
    assert versions.history("proposals", proposal["proposal_id"])
    assert any(
        event.action == "improvement_adopted" and event.outcome == "completed"
        for event in audit.get_events()
    )


def test_rejected_proposal_cannot_be_adopted(tmp_path):
    manager, audit, _, _ = _system(tmp_path)
    proposal = _proposal(manager)
    rejected = manager.reject_proposal(
        proposal["proposal_id"],
        reason="Risk is not acceptable.",
        rejected_by="owner",
    )

    assert rejected["status"] == "rejected"
    with pytest.raises(ValueError, match="must be approval"):
        manager.adopt_proposal(
            proposal["proposal_id"],
            permission_manager=_evolution_access(tmp_path, audit)[0],
            approval=None,
            requested_by="owner",
        )


def test_adoption_needs_permission_and_rollback_restores_sandbox_state(tmp_path):
    manager, audit, _, versions = _system(tmp_path)
    proposal = _proposal(manager)
    manager.sandbox_proposal(
        proposal["proposal_id"], report="Validated locally; no code executed."
    )
    permissions, approvals = _evolution_access(tmp_path, audit)
    adoption_id, adoption = manager.request_adoption_approval(
        proposal["proposal_id"],
        approval_manager=approvals,
        approved_by="owner",
        created_by="requester",
        reason="Adoption review.",
    )
    approvals.approve_approval(adoption_id, approved_by="owner")
    permissions.get_permission(EVOLUTION_PERMISSION).revoke()
    denied = manager.adopt_proposal(
        proposal["proposal_id"],
        permission_manager=permissions,
        approval=adoption,
        requested_by="owner",
    )
    assert denied.status == "failed"
    assert manager.get_proposal(proposal["proposal_id"])["status"] == "approval"
    permissions.get_permission(EVOLUTION_PERMISSION).grant()
    # The original task-bound approval remains unused after the permission denial.
    approved = manager.adopt_proposal(
        proposal["proposal_id"],
        permission_manager=permissions,
        approval=adoption,
        requested_by="owner",
    )
    assert approved.status == "completed"

    rollback_id, rollback_approval = manager.request_rollback_approval(
        proposal["proposal_id"],
        approval_manager=approvals,
        approved_by="owner",
        created_by="requester",
        reason="Rollback after review.",
    )
    approvals.approve_approval(rollback_id, approved_by="owner")
    rollback = manager.rollback_proposal(
        proposal["proposal_id"],
        permission_manager=permissions,
        approval=rollback_approval,
        requested_by="owner",
        reason="Restore proposal to sandbox for further review.",
    )

    assert rollback.status == "completed"
    rolled_back = manager.get_proposal(proposal["proposal_id"])
    assert rolled_back["status"] == "sandbox"
    assert "approval_status" not in rolled_back
    changes = manager.list_records("change_log")
    assert changes[-1]["reason"].startswith("adopted -> sandbox")
    assert changes[-1]["approval_status"] == "approved"
    assert len(versions.history("proposals", proposal["proposal_id"])) >= 4


def test_knowledge_records_can_be_updated_and_deleted_with_provenance(tmp_path):
    manager, audit, events, _ = _system(tmp_path)
    record = manager.add_knowledge(
        "Local validation checklist.",
        source="user://notes/checklist",
    )
    updated = manager.update_knowledge(
        record["knowledge_id"],
        content="Updated local validation checklist.",
        source="user://notes/checklist-v2",
    )

    assert updated["source"] == "user://notes/checklist-v2"
    assert updated["content"] == "Updated local validation checklist."
    assert datetime.fromisoformat(updated["updated_at"]) >= datetime.fromisoformat(
        record["created_at"]
    )
    assert manager.delete_knowledge(record["knowledge_id"])
    assert manager.list_records("knowledge") == []
    assert {
        event.action for event in audit.get_events()
    } >= {"knowledge_added", "knowledge_updated", "knowledge_deleted"}
    assert events.get_events(entity_type="knowledge", entity_id=record["knowledge_id"])


def test_experience_lessons_are_recalled_with_source_and_lifecycle_is_audited(
    tmp_path,
):
    manager, audit, events, _ = _system(tmp_path)
    matching = manager.add_knowledge(
        "نجح التدريب على حلقات Python عبر تمارين قصيرة يومية.",
        source="task://task-python",
        metadata={"kind": "experience_lesson", "outcome": "success"},
    )
    unrelated = manager.add_knowledge(
        "Observed failure: the garden watering schedule missed two days.",
        source="task://task-garden",
        metadata={"kind": "experience_lesson", "outcome": "failure"},
    )
    other_knowledge = manager.add_knowledge(
        "Python uses indentation to define blocks.",
        source="user://note-python",
        metadata={"kind": "user_note"},
    )

    results = manager.recall_experience_lessons("تدريب حلقات Python", limit=5)

    assert [item["knowledge_id"] for item in results] == [matching["knowledge_id"]]
    assert results[0]["source"] == "task://task-python"
    assert results[0]["outcome"] == "success"
    assert other_knowledge["knowledge_id"] not in {
        item["knowledge_id"] for item in results
    }

    manager.set_experience_lesson_active(matching["knowledge_id"], active=False)
    assert manager.recall_experience_lessons("حلقات Python") == []
    assert matching["knowledge_id"] in {
        item["knowledge_id"]
        for item in manager.list_experience_lessons(include_inactive=True)
    }
    manager.set_experience_lesson_active(matching["knowledge_id"], active=True)
    assert manager.recall_experience_lessons("حلقات Python")
    manager.delete_experience_lesson(unrelated["knowledge_id"])
    assert all(
        item["knowledge_id"] != unrelated["knowledge_id"]
        for item in manager.list_experience_lessons()
    )
    assert {
        item.action for item in audit.get_events()
    } >= {
        "experience_lessons_recalled",
        "knowledge_updated",
        "knowledge_deleted",
    }
    assert events.get_events(entity_type="knowledge")


def test_starter_marketing_lessons_are_curated_and_idempotent(tmp_path):
    manager, _, _, _ = _system(tmp_path)

    added = manager.add_starter_marketing_lessons(changed_by="test")
    added_again = manager.add_starter_marketing_lessons(changed_by="test")

    assert len(added) == 5
    assert added_again == []
    assert all(
        item["metadata"]["origin"] == "curated_starter"
        and item["source"].startswith("booda://starter/marketing/")
        for item in added
    )
    results = manager.recall_experience_lessons("اعمل خطة للتسويق والإعلان")
    assert results
    assert all(item["origin"] == "curated_starter" for item in results)


def test_agent_adds_relevant_experience_lessons_to_planning_context(tmp_path):
    manager, _, _, _ = _system(tmp_path)
    manager.add_knowledge(
        "مبتدئ Python تعلم الحلقات عبر تمارين قصيرة يومية.",
        source="task://previous-python-task",
        metadata={"kind": "experience_lesson", "outcome": "success"},
    )

    class ContextPlanner:
        def __init__(self):
            self.memory = None

        def create_plan(self, goal, memory):
            self.memory = memory
            return BoodaPlan(
                goal.goal_id,
                (PlanStep("study-next", "Practice next topic"),),
            )

    planner = ContextPlanner()
    agent = BoodaAgent(
        planner,
        BoodaTaskManager(),
        BoodaToolRegistry(),
        BoodaExecutor(),
        evolution_manager=manager,
    )
    agent.intake(BoodaGoal("study-next", "تعلم الحلقات في Python"))
    agent.plan()

    lesson = planner.memory["experience_lessons"][0]
    assert lesson["source"] == "task://previous-python-task"
    assert "مبتدئ Python" in lesson["content"]
