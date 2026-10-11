from datetime import datetime, timedelta, timezone

from core.goal_manager import BoodaGoalManager
from core.main import show_dashboard
from core.planning import BoodaGoal
from core.project_manager import BoodaProjectManager
from core.task_manager import BoodaTaskManager


def test_dashboard_summarizes_statuses_and_deadlines(tmp_path, capsys):
    goals = BoodaGoalManager(tmp_path / "goals.json")
    goals.add_goal(BoodaGoal("goal-1", "Launch campaign"))
    goals.add_goal(BoodaGoal("goal-2", "Learn design"))
    goals.update_status("goal-2", "paused")

    projects = BoodaProjectManager(tmp_path / "projects.json")
    projects.add_project("project-1", "Autumn campaign")

    tasks = BoodaTaskManager(tmp_path / "tasks.json")
    tasks.add_task("late", "Review brief", due_at="2026-10-07T11:00:00+03:00")
    tasks.add_task("soon", "Prepare draft", due_at="2026-10-09T11:00:00+03:00")
    tasks.add_task("done", "Finished task").complete()
    as_of = datetime(2026, 10, 8, 12, tzinfo=timezone(timedelta(hours=3)))

    show_dashboard(goals, projects, tasks, as_of=as_of)

    output = capsys.readouterr().out
    assert "الأهداف: 2 (نشطة: 1, متوقفة: 1" in output
    assert "المشاريع: 1 (نشطة: 1" in output
    assert "المهام: 3 (معلّقة: 2" in output
    assert "متأخرة 1" in output
    assert "Review brief [late]" in output
    assert "Prepare draft [soon]" in output
    assert "Finished task" not in output


def test_dashboard_handles_an_empty_project(tmp_path, capsys):
    show_dashboard(
        BoodaGoalManager(tmp_path / "goals.json"),
        BoodaProjectManager(tmp_path / "projects.json"),
        BoodaTaskManager(tmp_path / "tasks.json"),
    )

    output = capsys.readouterr().out
    assert "الأهداف: 0" in output
    assert "المشاريع: 0" in output
    assert "المهام: 0" in output
