from core.goal_manager import BoodaGoalManager
from core.main import create_goal
from core.project_manager import BoodaProjectManager


def test_goal_and_project_menu_flow_preserves_link(monkeypatch, tmp_path, capsys):
    project_manager = BoodaProjectManager(tmp_path / "projects.json")
    project_manager.add_project("project-1", "Campaign")
    goal_manager = BoodaGoalManager(tmp_path / "goals.json")
    answers = iter(["goal-1", "Learn ads", "project-1"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    create_goal(goal_manager, project_manager)

    restored = BoodaGoalManager(tmp_path / "goals.json").get_goal("goal-1")
    assert restored.goal.context["project_id"] == "project-1"
    assert restored.project_id == "project-1"
    assert "تم حفظ الهدف" in capsys.readouterr().out
