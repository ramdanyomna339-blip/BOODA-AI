from datetime import datetime, timezone

from core.main import create_project, create_task, show_projects
from core.goal_manager import BoodaGoalManager
from core.planning import BoodaGoal
from core.project_manager import BoodaProjectManager
from core.scheduler import BoodaScheduler
from core.task_manager import BoodaTaskManager


def test_project_and_task_links_persist(tmp_path):
    project_path = tmp_path / "memory" / "projects.json"
    task_path = tmp_path / "memory" / "tasks.json"

    projects = BoodaProjectManager(project_path)
    project = projects.add_project(
        "campaign-001",
        "Launch campaign",
        goal_id="goal-001",
        due_at="2026-10-22",
    )
    tasks = BoodaTaskManager(task_path)
    tasks.add_task(
        "task-001",
        "Review brief",
        project_id=project.project_id,
        due_at="2026-10-10T17:00:00+03:00",
    )

    restored_projects = BoodaProjectManager(project_path)
    restored_tasks = BoodaTaskManager(task_path)

    assert restored_projects.get_project("campaign-001").goal_id == "goal-001"
    assert restored_projects.get_project("campaign-001").due_at == "2026-10-22"
    task = restored_tasks.get_task("task-001")
    assert task.project_id == "campaign-001"
    assert task.due_at == "2026-10-10T17:00:00+03:00"


def test_scheduler_separates_overdue_upcoming_and_completed_tasks():
    task_manager = BoodaTaskManager()
    task_manager.add_task("late", "Late", due_at="2026-10-07T12:00:00Z")
    task_manager.add_task("soon", "Soon", due_at="2026-10-09T12:00:00Z")
    task_manager.add_task("done", "Done", due_at="2026-10-09T13:00:00Z").complete()
    scheduler = BoodaScheduler(task_manager)
    as_of = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)

    assert [task.task_id for task in scheduler.get_overdue_tasks(as_of=as_of)] == ["late"]
    assert [task.task_id for task in scheduler.get_upcoming_tasks(as_of=as_of)] == ["soon"]


def test_project_update_validates_status_and_persists(tmp_path):
    file_path = tmp_path / "projects.json"
    manager = BoodaProjectManager(file_path)
    manager.add_project("project-1", "Project")

    updated = manager.update_project("project-1", status="completed")

    assert updated.status == "completed"
    assert BoodaProjectManager(file_path).get_project("project-1").status == "completed"


def test_project_and_task_creation_flow_is_connected(monkeypatch, tmp_path, capsys):
    projects = BoodaProjectManager(tmp_path / "projects.json")
    goals = BoodaGoalManager(tmp_path / "goals.json")
    goals.add_goal(BoodaGoal("goal-1", "Grow sales"))
    tasks = BoodaTaskManager(tmp_path / "tasks.json")
    answers = iter([
        "project-1", "Launch", "Campaign project", "goal-1", "2026-10-22",
        "task-1", "Review brief", "Check claims", "project-1",
        "2026-10-10T17:00:00+03:00",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    create_project(projects, goals)
    create_task(tasks, projects)
    show_projects(projects, tasks)

    assert tasks.get_task("task-1").project_id == "project-1"
    assert "المهام: 1" in capsys.readouterr().out
