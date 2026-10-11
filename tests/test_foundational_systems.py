import pytest

from core.artifact_manager import BoodaArtifactManager
from core.brain import BoodaAgent
from core.capability_registry import BoodaCapabilityRegistry
from core.event_log import BoodaEventLog
from core.executor import BoodaExecutor
from core.goal_manager import BoodaGoalManager
from core.jobs import BoodaJobManager, BoodaJobRunner
from core.learning import BoodaLearningManager
from core.planning import BoodaGoal, BoodaPlan, PlanStep
from core.task_manager import BoodaTaskManager
from core.tool_registry import BoodaToolRegistry
from core.versioning import BoodaVersionStore


def test_goal_lifecycle_persists_and_agent_links_generated_tasks(tmp_path):
    events = BoodaEventLog(tmp_path / "events.jsonl")
    versions = BoodaVersionStore(tmp_path / "versions.jsonl")
    goals = BoodaGoalManager(tmp_path / "goals.json", version_store=versions, event_log=events)
    tasks = BoodaTaskManager(tmp_path / "tasks.json", version_store=versions, event_log=events)
    goal = BoodaGoal("goal-1", "Learn ads", {"project_id": "project-1"})

    class Planner:
        def create_plan(self, received_goal, _memory):
            return BoodaPlan(received_goal.goal_id, (
                PlanStep("lesson-1", "Study", due_at="2026-10-22"),
            ))

    agent = BoodaAgent(Planner(), tasks, BoodaToolRegistry(), BoodaExecutor(),
                       goal_manager=goals, event_log=events)
    agent.intake(goal)
    agent.plan()
    goals.update_status("goal-1", "paused")

    reopened_goals = BoodaGoalManager(tmp_path / "goals.json")
    task = tasks.get_task("lesson-1")
    assert reopened_goals.get_goal("goal-1").status == "paused"
    assert task.goal_id == "goal-1"
    assert task.project_id == "project-1"
    assert task.due_at == "2026-10-22"
    assert len(versions.history("goal", "goal-1")) == 2
    assert events.get_events(entity_type="goal", entity_id="goal-1")


def test_capability_registry_is_persistent_and_enforced(tmp_path):
    path = tmp_path / "capabilities.json"
    capabilities = BoodaCapabilityRegistry(path)
    capabilities.register("send", permission_name="send_message")
    registry = BoodaToolRegistry(capabilities)
    registry.register("send", lambda _task: "sent")
    capabilities.set_enabled("send", False)

    assert BoodaCapabilityRegistry(path).get("send").enabled is False
    assert registry.get("send") is None
    with pytest.raises(ValueError, match="disabled"):
        BoodaToolRegistry(capabilities).register("send", lambda: None)


def test_agent_rejects_plan_that_weakens_capability_permission(tmp_path):
    capabilities = BoodaCapabilityRegistry(tmp_path / "caps.json")
    capabilities.register("send", permission_name="send_message")
    registry = BoodaToolRegistry(capabilities)
    registry.register("send", lambda _task: "sent")

    class Planner:
        def create_plan(self, goal, _memory):
            return BoodaPlan(goal.goal_id, (
                PlanStep("send-task", "Send", capability="send"),
            ))

    agent = BoodaAgent(Planner(), BoodaTaskManager(), registry, BoodaExecutor())
    agent.intake(BoodaGoal("goal", "Send a message"))
    with pytest.raises(ValueError, match="does not match capability policy"):
        agent.plan()
    assert agent.task_manager.get_task("send-task") is None


def test_learning_path_tracks_progress_and_assessments(tmp_path):
    path = tmp_path / "learning.json"
    manager = BoodaLearningManager(path)
    manager.add_path("Ads basics", [{"unit_id": "u1", "title": "Brief"}],
                     path_id="path-1", goal_id="goal-1")
    progress = manager.update_unit_status("path-1", "u1", "completed")
    manager.record_assessment("path-1", score=85, feedback="Good", unit_id="u1")

    restored = BoodaLearningManager(path).get_path("path-1")
    assert progress["progress"] == 1.0
    assert restored["status"] == "completed"
    assert restored["assessments"][0]["score"] == 85


def test_job_queue_runs_registered_handlers_and_retries(tmp_path):
    manager = BoodaJobManager(tmp_path / "jobs.json")
    manager.enqueue("sum", {"values": [2, 3]}, job_id="job-1")
    result = BoodaJobRunner(manager, {"sum": lambda payload: sum(payload["values"])}).run_due()
    assert result[0]["status"] == "completed"
    assert manager.get("job-1")["result"] == 5

    manager.enqueue("flaky", {}, max_attempts=2, job_id="job-2")
    failed_runner = BoodaJobRunner(manager, {"flaky": lambda _payload: 1 / 0})
    assert failed_runner.run_due()[0]["status"] == "queued"
    assert failed_runner.run_due()[0]["status"] == "failed"


def test_artifact_catalog_and_domain_event_filters(tmp_path):
    artifact_path = tmp_path / "draft.txt"
    artifact_path.write_text("draft", encoding="utf-8")
    events = BoodaEventLog(tmp_path / "events.jsonl")
    artifacts = BoodaArtifactManager(tmp_path / "artifacts.json", event_log=events)
    artifact = artifacts.register(str(artifact_path), task_id="task-1", kind="draft")

    assert artifacts.list(task_id="task-1")[0]["artifact_id"] == artifact["artifact_id"]
    assert events.get_events(entity_type="artifact", event_type="artifact_registered")


def test_version_store_keeps_ordered_snapshots(tmp_path):
    versions = BoodaVersionStore(tmp_path / "versions.jsonl")
    versions.record("project", "p1", {"status": "active"})
    versions.record("project", "p1", {"status": "completed"})
    history = versions.history("project", "p1")

    assert [item["version"] for item in history] == [1, 2]
    assert history[-1]["snapshot"]["status"] == "completed"
