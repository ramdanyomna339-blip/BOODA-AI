"""Decision-loop orchestration for Booda, independent from any one tool."""

from dataclasses import dataclass, field
import time
from typing import Any, Protocol

from core.memory import NullBoodaMemory
from core.planning import BoodaGoal, BoodaPlan, PlanStep
from core.state import BoodaState
from core.task import BoodaTask
from core.task_manager import BoodaTaskManager


class BoodaPlanner(Protocol):
    def create_plan(self, goal: BoodaGoal, memory: Any) -> BoodaPlan: ...


class BoodaVerifier(Protocol):
    def verify(self, task: BoodaTask, result: Any, goal: BoodaGoal) -> bool: ...


@dataclass
class AgentState(BoodaState):
    goal: BoodaGoal | None = None
    plan: BoodaPlan | None = None
    phase: str = "idle"
    last_decision: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    conversation: list[dict[str, str]] = field(default_factory=list)
    interrupted_task_id: str | None = None
    replan_count: int = 0
    plan_reviewed: bool = False

    def __post_init__(self):
        BoodaState.__init__(self)


class BoodaAgent:
    """Runs one observable decision step at a time through existing guardrails."""

    def __init__(self, planner, task_manager, registry, executor, *,
                 permission_manager=None, permission_policy=None,
                 approval_provider=None, verifier=None, memory=None,
                 audit_log=None, requested_by=None,
                 state=None, goal_manager=None, event_log=None,
                 session_store=None, session_id="default", learning_manager=None,
                 evolution_manager=None, context_builder=None,
                 knowledge_base=None, structured_memory=None, research_manager=None):
        self.planner = planner
        self.task_manager = task_manager
        self.registry = registry
        self.executor = executor
        self.permission_manager = permission_manager
        self.permission_policy = permission_policy
        self.approval_provider = approval_provider
        self.verifier = verifier
        self.memory = memory or NullBoodaMemory()
        self.audit_log = audit_log
        self.requested_by = requested_by
        self.goal_manager = goal_manager
        self.event_log = event_log
        self.state = state or AgentState()
        self.session_store = session_store
        self.session_id = session_id
        self.learning_manager = learning_manager
        self.evolution_manager = evolution_manager
        self.context_builder = context_builder
        self.knowledge_base = knowledge_base
        self.structured_memory = structured_memory
        self.research_manager = research_manager
        self.require_plan_review = bool(
            getattr(self.planner, "requires_explicit_permissions", False)
        )
        self._steps = {}
        if getattr(self.planner, "requires_explicit_permissions", False):
            if self.permission_manager is None or self.permission_policy is None:
                raise ValueError(
                    "AI planning requires the configured permission manager and policy."
                )
            configure_agent = getattr(self.planner, "configure_agent", None)
            if not callable(configure_agent):
                raise TypeError("AI planner must support live capability configuration.")
            configure_agent(registry=self.registry, permission_manager=self.permission_manager)
        self._restore_session()

    def _restore_session(self):
        if self.session_store is None or self.state.goal is not None:
            return
        saved = self.session_store.load(self.session_id)
        if not saved:
            return
        goal_data = saved.get("goal")
        if goal_data is not None:
            self.state.goal = BoodaGoal(
                goal_data["goal_id"], goal_data["intent"], goal_data.get("context", {})
            )
        plan_data = saved.get("plan")
        if plan_data is not None:
            steps = tuple(PlanStep(**step) for step in plan_data.get("steps", ()))
            self.state.plan = BoodaPlan(
                plan_data["goal_id"], steps, plan_id=plan_data.get("plan_id", "plan-1")
            )
            self._steps = {step.task_id: step for step in steps}
        self.state.phase = saved.get("phase", "idle")
        self.state.plan_reviewed = saved.get("plan_reviewed", False)
        self.state.last_decision = saved.get("last_decision")
        self.state.history = list(saved.get("history", []))[-200:]
        self.state.conversation = list(saved.get("conversation", []))[-12:]
        self.state.replan_count = saved.get("replan_count", 0)
        active_task_id = saved.get("active_task_id")
        active_task = self.task_manager.get_task(active_task_id) if active_task_id else None
        if active_task is not None and active_task.status == "running":
            # An interrupted external action may have completed before the
            # process stopped. Never repeat it without an explicit retry.
            self.state.phase = "needs_attention"
            self.state.interrupted_task_id = active_task_id
        elif self.state.plan is not None:
            if not self.state.plan_reviewed:
                self.state.phase = "review_required"
            missing = [step.task_id for step in self.state.plan.steps
                       if self.task_manager.get_task(step.task_id) is None]
            if missing:
                existing = [self.task_manager.get_task(step.task_id)
                            for step in self.state.plan.steps]
                if all(task is None or task.status == "pending" for task in existing):
                    missing_specs = [{
                        "task_id": step.task_id,
                        "title": step.title,
                        "description": step.description,
                        "depends_on": step.depends_on,
                        "metadata": step.metadata,
                        "goal_id": self.state.goal.goal_id,
                        "project_id": self.state.goal.context.get("project_id"),
                        "due_at": step.due_at,
                    } for step in self.state.plan.steps
                        if self.task_manager.get_task(step.task_id) is None]
                    add_tasks = getattr(self.task_manager, "add_tasks", None)
                    if callable(add_tasks):
                        add_tasks(missing_specs)
                    else:
                        for spec in missing_specs:
                            self.task_manager.add_task(**spec)
                else:
                    self.state.phase = "needs_attention"
                    self.state.last_decision = f"missing persisted tasks: {', '.join(missing)}"
            if self.state.phase in {"planning", "running"}:
                self._update_phase()

    def _persist_state(self):
        if self.session_store is not None:
            self.session_store.save(self.session_id, self.state)

    def _record_experience(self, task):
        if self.evolution_manager is None or self.state.goal is None:
            return None
        return self.evolution_manager.record_task_result(
            task,
            goal=self.state.goal.intent,
            inputs_summary=task.description,
            result_summary=str(task.result or ""),
            recorded_by=self.requested_by or "agent",
        )

    def _record_research_outcome(self, task, started):
        if self.research_manager is None:
            return
        try:
            self.research_manager.record_task_outcome(task, duration_seconds=round(time.monotonic() - started, 6),
                                                      task_manager=self.task_manager)
        except Exception as error:
            # Observation failure must not trigger a repeat of an external action.
            self._record("research_observation_failed", {"task_id": task.task_id, "error": type(error).__name__})

    def intake(self, goal: BoodaGoal, *, replace_current=False):
        if self.state.phase in {"planning", "running"}:
            raise RuntimeError("Booda is already working on a goal.")
        terminal_phases = {"idle", "completed", "cancelled"}
        if (
            self.state.goal is not None
            and self.state.goal.goal_id != goal.goal_id
            and self.state.phase not in terminal_phases
            and not replace_current
        ):
            raise RuntimeError(
                "The current goal is unfinished; explicitly replace or finish it first."
            )
        if (
            replace_current and self.state.goal is not None
            and self.state.goal.goal_id != goal.goal_id
            and self.goal_manager is not None
        ):
            old = self.goal_manager.get_goal(self.state.goal.goal_id)
            if old is not None and old.status == "active":
                self.goal_manager.update_status(old.goal.goal_id, "paused")
        if self.goal_manager is not None:
            existing = self.goal_manager.get_goal(goal.goal_id)
            if existing is not None and existing.goal != goal:
                raise ValueError(f"Goal id already belongs to another goal: {goal.goal_id}")
        self.state.goal = goal
        self.state.plan = None
        self.state.replan_count = 0
        self.state.plan_reviewed = False
        self.state.interrupted_task_id = None
        self.state.clear_task()
        self.state.phase = "received"
        self.state.history.clear()
        self.state.conversation.clear()
        self._steps.clear()
        if self.goal_manager is not None:
            existing = self.goal_manager.get_goal(goal.goal_id)
            if existing is None:
                self.goal_manager.add_goal(
                    goal, project_id=goal.context.get("project_id")
                )
        self._record("goal_received", {"intent": goal.intent})
        return goal

    def plan(self):
        if self.state.goal is None:
            raise RuntimeError("Receive a goal before planning.")
        if self.state.plan is not None:
            raise RuntimeError("A plan already exists; resume it or use reviewed replanning.")
        self.state.phase = "planning"
        self._persist_state()
        try:
            planning_context = self._recall_context()
            plan = self.planner.create_plan(
                self.state.goal,
                planning_context,
            )
            if plan.goal_id != self.state.goal.goal_id:
                raise ValueError("Planner returned a plan for a different goal.")
            if not plan.steps:
                raise ValueError("Planner must return at least one actionable plan step.")
            self._validate_plan_capabilities(plan)
            # Validate the complete plan against persisted tasks before adding
            # any of it, so a collision cannot leave a partial plan behind.
            for step in plan.steps:
                if self.task_manager.get_task(step.task_id) is not None:
                    raise ValueError(f"Task already exists: {step.task_id}")
        except Exception:
            self.state.phase = "received"
            self._persist_state()
            raise
        self._steps = {step.task_id: step for step in plan.steps}
        self.state.plan = plan
        self.state.plan_reviewed = not self.require_plan_review
        self._persist_state()
        research_references = [{"research_id": f["research_id"], "finding_id": f["id"],
                                "revision": f.get("revision") or 1}
                               for f in (planning_context or {}).get("research_knowledge", [])] if isinstance(planning_context, dict) else []
        specs = [{
            "task_id": step.task_id,
            "title": step.title,
            "description": step.description,
            "depends_on": step.depends_on,
            "metadata": dict(step.metadata, research_references=research_references) if self.research_manager is not None else step.metadata,
            "goal_id": self.state.goal.goal_id,
            "project_id": self.state.goal.context.get("project_id"),
            "due_at": step.due_at,
        } for step in plan.steps]
        try:
            add_tasks = getattr(self.task_manager, "add_tasks", None)
            if callable(add_tasks):
                add_tasks(specs)
            else:
                for spec in specs:
                    self.task_manager.add_task(**spec)
        except Exception:
            self.state.plan = None
            self._steps.clear()
            self.state.phase = "received"
            self._persist_state()
            raise
        self.state.phase = (
            "review_required"
            if self.require_plan_review
            else ("ready" if plan.steps else "completed")
        )
        self._record("plan_created", {"plan_id": plan.plan_id, "task_ids": [s.task_id for s in plan.steps]})
        return plan

    def run_once(self):
        if self.state.goal is None or self.state.plan is None:
            raise RuntimeError("Receive a goal and create a plan before running.")
        if not self.state.plan_reviewed:
            raise RuntimeError("Review and approve the plan before execution.")
        by_id = {step.task_id: self.task_manager.get_task(step.task_id) for step in self.state.plan.steps}
        missing_tasks = [task_id for task_id, task in by_id.items() if task is None]
        if missing_tasks:
            self.state.phase = "needs_attention"
            self.state.last_decision = f"missing persisted tasks: {', '.join(missing_tasks)}"
            self._persist_state()
            return {"status": "missing_tasks", "task_ids": missing_tasks}
        for step in self.state.plan.steps:
            task = by_id[step.task_id]
            if task.status != "pending":
                continue
            dependencies = [by_id[item] for item in step.depends_on]
            if any(
                dependency.status in {"failed", "blocked", "uncertain"}
                for dependency in dependencies
            ):
                task.status = "blocked"
                task.result = "A dependency failed or has an uncertain outcome."
                task._notify_change()
                self._record_experience(task)
                self.state.phase = "needs_attention"
                self._record("task_blocked", {"task_id": task.task_id})
                return task
            if any(dependency.status != "completed" for dependency in dependencies):
                continue
            if step.metadata.get("input_bindings"):
                from core.dataflow import resolve_bindings
                try:
                    task.metadata = resolve_bindings(step, by_id, self._verification_status)
                    task._notify_change()
                except ValueError as error:
                    task.fail({"input_error": str(error), "action_executed": False})
                    self.state.phase = "needs_attention"
                    self._record("input_binding_failed", {"task_id": task.task_id})
                    return task
            if not self.state.set_task(task):
                return {"status": "agent_busy", "task": self.state.current_task}
            self.state.phase = "running"
            self.state.last_decision = f"execute:{task.task_id}"
            self._record("task_selected", {"task_id": task.task_id})
            if step.capability is None or self.registry.get(step.capability) is None:
                self.state.phase = "waiting_for_capability"
                self.state.clear_task()
                self._record("capability_missing", {"task_id": task.task_id, "capability": step.capability})
                if self.evolution_manager is not None and step.capability:
                    self.evolution_manager.create_capability_gap(
                        step.capability,
                        f"Planned task requires unavailable capability '{step.capability}'.",
                        detected_from=task.task_id,
                        required_tools=(step.capability,),
                        changed_by=self.requested_by or "agent",
                    )
                return {"status": "waiting_for_capability", "task": task}
            approval = self.approval_provider(task, step) if self.approval_provider else None
            permission = (
                self.permission_manager.get_permission(step.permission_name)
                if self.permission_manager is not None and step.permission_name is not None
                else None
            )
            if permission is not None and not permission.allowed:
                self.state.phase = "waiting_for_permission"
                self.state.clear_task()
                self._record("permission_missing", {
                    "task_id": task.task_id,
                    "permission_name": step.permission_name,
                })
                return {"status": "waiting_for_permission", "task": task}
            if step.permission_name is not None and permission is None:
                self.state.phase = "needs_attention"
                self.state.clear_task()
                self._record("permission_unregistered", {
                    "task_id": task.task_id,
                    "permission_name": step.permission_name,
                })
                return {"status": "permission_unregistered", "task": task}
            if (
                permission is not None
                and permission.allowed
                and self.permission_policy is not None
                and self.permission_policy.requires_approval(permission)
                and approval is None
            ):
                self.state.phase = "waiting_for_approval"
                self.state.clear_task()
                self._record("approval_missing", {
                    "task_id": task.task_id,
                    "permission_name": step.permission_name,
                })
                return {"status": "waiting_for_approval", "task": task}
            started = time.monotonic()
            try:
                result = self.executor.execute(
                    task=task,
                    action=lambda: self.registry.require(step.capability)(task),
                    permission_manager=self.permission_manager,
                    permission_name=step.permission_name,
                    permission_policy=self.permission_policy,
                    approval=approval,
                    audit_log=self.audit_log,
                    requested_by=self.requested_by,
                )
            except Exception:
                self.state.clear_task()
                self.state.phase = "needs_attention"
                self._persist_state()
                self._record_research_outcome(task, started)
                raise
            self.state.clear_task()
            if task.status == "completed" and self.verifier is not None:
                try:
                    verified = self.verifier.verify(task, result, self.state.goal)
                except Exception as error:
                    task.mark_uncertain({
                        "action_result": result,
                        "verification_error": type(error).__name__,
                    })
                    self._record("verification_uncertain", {"task_id": task.task_id})
                    self._record_research_outcome(task, started)
                    self._update_phase()
                    return task
                if verified is None:
                    self._record("verification_unavailable", {"task_id": task.task_id})
                elif not verified:
                    task.fail({"action_result": result, "verification": "failed", "action_executed": True})
                    self._record("verification_failed", {"task_id": task.task_id})
                else:
                    self._record("verification_passed", {"task_id": task.task_id})
            if task.status in {"completed", "failed", "blocked"}:
                self._record_experience(task)
            self._record_research_outcome(task, started)
            self._record("task_finished", {"task_id": task.task_id, "status": task.status})
            self._update_phase()
            return task
        self._update_phase()
        return None

    def retry_interrupted_task(self, task_id):
        if task_id != self.state.interrupted_task_id:
            raise ValueError("Task is not awaiting an explicit retry decision.")
        task = self.task_manager.get_task(task_id)
        if task is None or task.status != "running":
            raise ValueError("Interrupted task state no longer matches the saved session.")
        task.status = "pending"
        task.result = None
        task._notify_change()
        self.state.interrupted_task_id = None
        self.state.phase = "ready"
        self._record("interrupted_task_retry_authorized", {"task_id": task_id})
        return task

    def replan(self, reason):
        """Build a new, review-gated plan after a failed or blocked plan."""
        if self.state.goal is None or self.state.plan is None:
            raise RuntimeError("A planned goal is required before replanning.")
        if self.state.phase != "needs_attention":
            raise RuntimeError("Replanning is available only when work needs attention.")
        if self.state.replan_count >= 3:
            raise RuntimeError("The goal has reached its maximum of three replans.")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("A short replan reason is required.")
        previous_tasks = [
            self.task_manager.get_task(step.task_id) for step in self.state.plan.steps
        ]
        recovery_context = {
            "replan_request": reason.strip(),
            "previous_plan_id": self.state.plan.plan_id,
            "completed_tasks": [
                {"task_id": task.task_id, "title": task.title, "result": task.result}
                for task in previous_tasks if task is not None and task.status == "completed"
            ],
            "failed_or_blocked_tasks": [
                {"task_id": task.task_id, "title": task.title,
                 "status": task.status, "result": task.result}
                for task in previous_tasks if task is not None
                and task.status in {"failed", "blocked"}
            ],
            "uncertain_tasks": [
                {"task_id": task.task_id, "title": task.title, "result": task.result}
                for task in previous_tasks
                if task is not None and task.status == "uncertain"
            ],
            "memory": self._recall_context(),
        }
        new_plan = self.planner.create_plan(self.state.goal, recovery_context)
        if new_plan.goal_id != self.state.goal.goal_id:
            raise ValueError("Planner returned a replan for a different goal.")
        if not new_plan.steps:
            raise ValueError("The revised plan must include at least one step.")
        completed_signatures = {
            (task.title.strip().casefold(), self._steps[task.task_id].capability)
            for task in previous_tasks if task is not None and task.status == "completed"
        }
        repeats_completed = [
            step.title for step in new_plan.steps
            if (step.title.strip().casefold(), step.capability) in completed_signatures
        ]
        if repeats_completed:
            raise ValueError(
                "Revised plan repeats completed work: " + ", ".join(repeats_completed)
            )
        uncertain_capabilities = {
            self._steps[task.task_id].capability
            for task in previous_tasks if task is not None and (
                task.status == "uncertain" or (
                    task.status == "failed" and isinstance(task.result, dict)
                    and task.result.get("action_executed") is True
                )
            )
        }
        if any(step.capability in uncertain_capabilities for step in new_plan.steps):
            raise ValueError("Revised plan cannot repeat a capability with an unresolved uncertain action or an already executed action.")
        revision = self.state.replan_count + 1
        id_map = {
            step.task_id: f"{self.state.goal.goal_id}-revision-{revision}-{index}"
            for index, step in enumerate(new_plan.steps, start=1)
        }
        from copy import deepcopy
        def revision_metadata(step):
            metadata = deepcopy(step.metadata)
            for binding in metadata.get("input_bindings", {}).values():
                binding["task_id"] = id_map[binding["task_id"]]
            return metadata
        revised_steps = tuple(PlanStep(
            task_id=id_map[step.task_id],
            title=step.title,
            description=step.description,
            capability=step.capability,
            depends_on=tuple(id_map[item] for item in step.depends_on),
            permission_name=step.permission_name,
            metadata=revision_metadata(step),
            due_at=step.due_at,
        ) for step in new_plan.steps)
        plan = BoodaPlan(
            self.state.goal.goal_id,
            revised_steps,
            plan_id=f"{new_plan.plan_id}-revision-{revision}",
        )
        self._validate_plan_capabilities(plan)
        replan_memory = recovery_context.get("memory")
        research_references = [{"research_id": f["research_id"], "finding_id": f["id"],
                                "revision": f.get("revision") or 1}
                               for f in replan_memory.get("research_knowledge", [])] if isinstance(replan_memory, dict) else []
        specs = [{
            "task_id": step.task_id,
            "title": step.title,
            "description": step.description,
            "depends_on": step.depends_on,
            "metadata": dict(step.metadata, research_references=research_references) if self.research_manager is not None else step.metadata,
            "goal_id": self.state.goal.goal_id,
            "project_id": self.state.goal.context.get("project_id"),
            "due_at": step.due_at,
        } for step in plan.steps]
        previous_plan = self.state.plan
        previous_steps = self._steps
        previous_count = self.state.replan_count
        self.state.plan = plan
        self._steps = {step.task_id: step for step in plan.steps}
        self.state.replan_count = revision
        self.state.plan_reviewed = False
        self.state.phase = "review_required"
        self._persist_state()
        try:
            self.task_manager.add_tasks(specs)
        except Exception:
            self.state.plan = previous_plan
            self._steps = previous_steps
            self.state.replan_count = previous_count
            self.state.phase = "needs_attention"
            self._persist_state()
            raise
        self._record("replan_created", {
            "plan_id": plan.plan_id,
            "reason": reason.strip(),
            "task_ids": list(id_map.values()),
        })
        return plan

    def approve_plan(self, plan_id):
        if self.state.plan is None or self.state.plan_reviewed:
            raise RuntimeError("There is no unreviewed plan awaiting approval.")
        if self.state.plan.plan_id != plan_id:
            raise ValueError("The plan id does not match the plan awaiting review.")
        action = (
            "replan_approved"
            if self.state.replan_count
            and self.state.plan.plan_id.endswith(f"-revision-{self.state.replan_count}")
            else "plan_approved"
        )
        self.state.plan_reviewed = True
        self.state.phase = "ready"
        if self.audit_log is not None:
            self.audit_log.record(
                action=action,
                task_id=plan_id,
                task_title="User reviewed agent plan",
                requested_by=self.requested_by,
                outcome="completed",
            )
        self._record(action, {"plan_id": plan_id})
        return self.state.plan

    def approve_replan(self, plan_id):
        if self.state.phase != "review_required" or self.state.plan is None:
            raise RuntimeError("There is no revised plan awaiting approval.")
        return self.approve_plan(plan_id)

    def _validate_plan_capabilities(self, plan):
        capability_registry = getattr(self.registry, "capability_registry", None)
        if capability_registry is None:
            return
        for step in plan.steps:
            if step.capability is None:
                continue
            definition = capability_registry.get(step.capability)
            if definition is None:
                raise ValueError(f"Capability is not registered: {step.capability}")
            if step.permission_name != definition.permission_name:
                raise ValueError(
                    f"Planner permission does not match capability policy: {step.capability}"
                )

    def _recall_context(self, *, task_id=None, query=None):
        if self.state.goal is None:
            return None
        retrieval_goal = BoodaGoal(
            self.state.goal.goal_id,
            query if query is not None else self.state.goal.intent,
            self.state.goal.context,
        )
        recall_context = getattr(self.memory, "recall_context", None)
        if callable(recall_context):
            context = recall_context(self.state.goal)
        else:
            context = self.memory.recall(self.state.goal.goal_id)
        if self.structured_memory is not None:
            if not isinstance(context, dict):
                context = {"prior_memory": context} if context is not None else {}
            context["structured_memory"] = self.structured_memory.recall_context(
                retrieval_goal,
            )
        if self.learning_manager is not None:
            if not isinstance(context, dict):
                context = {"prior_memory": context} if context is not None else {}
            context["learning_paths"] = self.learning_manager.list_paths(
                goal_id=self.state.goal.goal_id
            )
            from core.marketing_course import recall_marketing_material

            context["learning_materials"] = recall_marketing_material(
                self.learning_manager,
                retrieval_goal.intent,
                limit=5,
            )
        if self.evolution_manager is not None:
            if not isinstance(context, dict):
                context = {"prior_memory": context} if context is not None else {}
            recall_lessons = getattr(
                self.evolution_manager, "recall_experience_lessons", None
            )
            if callable(recall_lessons):
                context["experience_lessons"] = recall_lessons(
                    retrieval_goal.intent, limit=5
                )
        if self.knowledge_base is not None:
            if not isinstance(context, dict):
                context = {"prior_memory": context} if context is not None else {}
            context["local_sources"] = self.knowledge_base.search(
                retrieval_goal.intent, limit=5,
                **{key: retrieval_goal.context[key] for key in ("project_id", "client_id")
                   if retrieval_goal.context.get(key) is not None},
            )
        if self.research_manager is not None:
            if not isinstance(context, dict):
                context = {"prior_memory": context} if context is not None else {}
            context["research_knowledge"] = self.research_manager.approved_knowledge(
                retrieval_goal.intent, limit=5
            )
        if self.context_builder is not None:
            context = self.context_builder.build(
                self.state.goal,
                context,
                task_id=task_id,
            )
        return context

    def respond(self, message):
        """Answer a conversational turn using goal state and relevant memory."""
        if not isinstance(message, str) or not message.strip():
            raise ValueError("Message must not be empty.")
        from core.calculator import calculate_request
        calculated = calculate_request(message)
        if calculated is not None:
            return self._finish_conversation(message, calculated)
        if any(phrase in message for phrase in ("تقدر تعمل إيه", "الأدوات المتاحة", "ايه الأدوات", "إمكانياتك")):
            tools = self.available_capabilities()
            answer = "الأدوات المتصلة بالجلسة: " + ("، ".join(
                item["name"] + (" (صلاحيتها متاحة)" if item["allowed"] else " (تحتاج صلاحية)")
                for item in tools) or "لا توجد أدوات متاحة")
            return self._finish_conversation(message, answer + ". وجود أداة لا يعني أني نفذتها؛ التنفيذ يمر بمراجعة الخطة والموافقات المطلوبة.")
        if any(phrase in message for phrase in ("وصلنا لفين", "إيه اللي اتنفذ", "ايه اللي اتنفذ", "حالة الهدف", "حالة التنفيذ")):
            lines = ["الحالة المسجلة: " + self.state.phase]
            if self.state.plan is None:
                lines.append("لا توجد خطة تنفيذ مسجلة.")
            else:
                for step in self.state.plan.steps:
                    task = self.task_manager.get_task(step.task_id)
                    lines.append(step.title + ": " + (task.status if task else "missing"))
                if all(step.capability == "create_plan_artifact" for step in self.state.plan.steps):
                    lines.append("هذه أدوات حفظ خطة؛ اكتمالها لا يعني تنفيذ الهدف خارج التطبيق.")
                else:
                    lines.append("اكتمال الأداة لا يثبت جودة النتيجة أو تحقق هدف خارج التطبيق.")
            return self._finish_conversation(message, "\n".join(lines))
        from core.reasoning_checks import checked_percentage_conflict, describe_review
        checked_answer = checked_percentage_conflict(message)
        if checked_answer is not None:
            return self._finish_conversation(message, checked_answer)
        if self.state.plan is not None and ("review_output" in message or (
            any(word in message for word in ("المخرج", "التصميم"))
            and any(word in message for word in ("عيوب", "جاهز", "راجع"))
        )):
            for step in reversed(self.state.plan.steps):
                task = self.task_manager.get_task(step.task_id)
                if step.capability == "review_output" and task is not None and task.status == "completed" and isinstance(task.result, dict):
                    checked_answer = describe_review(task.result)
                    if checked_answer is not None:
                        return self._finish_conversation(message, checked_answer)
        responder = getattr(self.planner, "respond", None)
        if not callable(responder):
            raise TypeError("The configured planner does not support conversation.")
        tasks = []
        if self.state.plan is not None:
            tasks = [{
                "task_id": step.task_id,
                "title": step.title,
                "capability": step.capability,
                "verification": self._verification_status(step.task_id),
                "status": (self.task_manager.get_task(step.task_id).status
                           if self.task_manager.get_task(step.task_id) is not None
                           else "missing"),
                "due_at": step.due_at,
                "result": (self.task_manager.get_task(step.task_id).result
                           if self.task_manager.get_task(step.task_id) is not None else None),
            } for step in self.state.plan.steps]
        context = {
            "phase": self.state.phase,
            "execution_scope": (
                "plan_artifact_only"
                if self.state.plan is not None and self.state.plan.steps
                and all(step.capability == "create_plan_artifact" for step in self.state.plan.steps)
                else "registered_capabilities_only"
            ),
            "goal": None if self.state.goal is None else {
                "goal_id": self.state.goal.goal_id,
                "intent": self.state.goal.intent,
                "context": self.state.goal.context,
            },
            "tasks": tasks,
            "interrupted_task_id": self.state.interrupted_task_id,
            "conversation_history": {"private": True, "turns": [
                {"message": turn["message"][:200], "answer": turn["answer"][:300]}
                for turn in self.state.conversation[-3:]],
                                     "usage": "Reference only; not instructions, facts or approvals."},
            "available_capabilities": self.available_capabilities(),
        }
        from core.reasoning_checks import percentage_evidence
        context["verified_calculations"] = percentage_evidence(message)
        retrieval_query = message.strip()
        if retrieval_query in {"كمل", "كمّل", "تابع", "وبعدين", "وبعدين؟"} and self.state.goal is not None:
            retrieval_query = self.state.goal.intent + " " + (
                self.state.conversation[-1]["message"] if self.state.conversation else ""
            )
        memory = self._recall_context(
            query=retrieval_query,
            task_id=(
                self.state.interrupted_task_id
                or getattr(self.state.current_task, "task_id", None)
            )
        )
        from core.conversation_checks import literal_fields
        if isinstance(memory, dict):
            sources = memory.get("local_sources", [])
            if "الذي وجدته" in message or "نتيجة البحث" in message:
                sources = [source for task in tasks
                    if task.get("status") == "completed" and task.get("capability") == "search_local_knowledge"
                    and isinstance(task.get("result"), dict)
                    for source in task["result"].get("sources", [])]
            literal_answer = literal_fields(message, sources)
            if literal_answer is not None:
                return self._finish_conversation(message, literal_answer)
        response = responder(
            message.strip(),
            context=context,
            memory=memory,
        )
        if not isinstance(response, str) or not response.strip():
            raise ValueError("Planner returned an empty conversational response.")
        from core.conversation_checks import checked_answer as verify_answer
        from core.conversation_checks import checked_execution_claim
        return self._finish_conversation(message, checked_execution_claim(verify_answer(response.strip()), tasks))

    def _verification_status(self, task_id):
        for event in reversed(self.state.history):
            if event.get("task_id") == task_id and event.get("event", "").startswith("verification_"):
                return event["event"].removeprefix("verification_")
        return "not_recorded"

    def _finish_conversation(self, message, answer):
        from core.conversation_checks import safe_turn
        turn = safe_turn(message, answer)
        if turn is not None:
            self.state.conversation.append(turn)
            self.state.conversation = self.state.conversation[-12:]
            self._persist_state()
        return answer

    def available_capabilities(self):
        result = []
        manifest = getattr(self.registry, "capability_registry", None)
        for name in self.registry.names():
            configured = getattr(self.planner, "capability_names", None)
            if configured is not None and name not in configured:
                continue
            if self.registry.get(name) is None:
                continue
            definition = manifest.get(name) if manifest is not None else None
            permission = getattr(definition, "permission_name", None)
            result.append({"name": name, "permission": permission,
                           "allowed": bool(self.permission_manager and permission
                                           and self.permission_manager.is_allowed(permission))})
        return result

    def record_user_correction(self, wrong, correction, reason, *, user_confirmed=False):
        if self.structured_memory is None:
            raise RuntimeError("Structured memory is not configured.")
        if any(not isinstance(value, str) or not value.strip() for value in (wrong, correction, reason)):
            raise ValueError("Correction requires original error, corrected statement and reason.")
        from uuid import uuid4
        context = self.state.goal.context if self.state.goal is not None else {}
        scope = "client" if context.get("client_id") else "project" if context.get("project_id") else "user"
        return self.structured_memory.add_confirmed(
            "lesson", "correction-" + uuid4().hex,
            {"wrong": wrong, "correction": correction, "reason": reason},
            scope=scope, scope_id=context.get(scope + "_id"),
            source="explicit-user-correction", rationale=reason,
            user_confirmed=user_confirmed,
        )

    def run_until_blocked(self, max_steps=None):
        """Advance ready work until complete, waiting, or needing attention.

        The default limit is the number of planned tasks, keeping each run
        bounded even when a capability or executor behaves unexpectedly.
        Outcomes are returned in execution order for callers and UIs.
        """
        if self.state.goal is None or self.state.plan is None:
            raise RuntimeError("Receive a goal and create a plan before running.")
        if max_steps is None:
            max_steps = len(self.state.plan.steps)
        if not isinstance(max_steps, int) or isinstance(max_steps, bool) or max_steps < 0:
            raise ValueError("max_steps must be a non-negative integer.")

        outcomes = []
        for _ in range(max_steps):
            outcome = self.run_once()
            if outcome is None:
                break
            outcomes.append(outcome)
            if isinstance(outcome, dict) or self.state.phase in {
                "completed", "needs_attention", "waiting_for_capability"
            }:
                break
        return outcomes

    def _update_phase(self):
        if self.state.plan is None:
            self.state.phase = "idle"
            self._persist_state()
            return
        tasks = [self.task_manager.get_task(step.task_id) for step in self.state.plan.steps]
        if any(task is None for task in tasks):
            self.state.phase = "needs_attention"
        elif all(task.status == "completed" for task in tasks):
            self.state.phase = "completed"
            if self.goal_manager is not None and self.state.goal is not None:
                record = self.goal_manager.get_goal(self.state.goal.goal_id)
                if record is not None and record.status != "completed":
                    self.goal_manager.update_status(self.state.goal.goal_id, "completed")
        elif any(task.status == "failed" for task in tasks):
            self.state.phase = "needs_attention"
        elif any(task.status == "blocked" for task in tasks):
            self.state.phase = "needs_attention"
        elif any(task.status == "uncertain" for task in tasks):
            self.state.phase = "needs_attention"
        elif any(task.status == "running" for task in tasks):
            self.state.phase = "needs_attention"
        else:
            self.state.phase = "ready"
        self._persist_state()

    def _record(self, event, details):
        entry = {"event": event, **details}
        self.state.history.append(entry)
        if self.state.goal is not None:
            self.memory.remember(self.state.goal.goal_id, entry)
            if self.event_log is not None:
                self.event_log.record(
                    event,
                    entity_type="goal",
                    entity_id=self.state.goal.goal_id,
                    details=details,
                )
        self._persist_state()
