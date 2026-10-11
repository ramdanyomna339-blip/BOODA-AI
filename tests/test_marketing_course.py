import builtins

from core.audit_log import BoodaAuditLog
from core.brain import BoodaAgent
from core.event_log import BoodaEventLog
from core.evolution_manager import BoodaEvolutionManager
from core.executor import BoodaExecutor
from core.learning import BoodaLearningManager
from core.main import manage_experience_lessons, manage_learning_course
from core.marketing_course import (
    MARKETING_CURRICULUM,
    MARKETING_PATH_ID,
    ensure_marketing_path,
    recall_marketing_material,
)
from core.planning import BoodaGoal, BoodaPlan, PlanStep
from core.task_manager import BoodaTaskManager
from core.tool_registry import BoodaToolRegistry


def test_marketing_material_is_seeded_idempotently_and_recalled_by_goal(tmp_path):
    manager = BoodaLearningManager(tmp_path / "learning.json")

    path = ensure_marketing_path(manager)
    second_seed = ensure_marketing_path(manager)
    results = recall_marketing_material(
        manager, "كيف أحسن قياس نتائج الإعلان؟"
    )

    assert len(MARKETING_CURRICULUM) == 5
    assert len(path["units"]) == 5
    assert second_seed["path_id"] == path["path_id"] == MARKETING_PATH_ID
    assert results
    assert any("قياس" in item["title"] for item in results)
    assert all(
        item["origin"] == "curated_starter"
        and item["source"].startswith("booda://starter/marketing/")
        for item in results
    )
    assert all("quiz" not in item for item in results)


def test_every_marketing_lesson_has_a_valid_practical_task_and_quiz():
    assert len(MARKETING_CURRICULUM) == 5
    for lesson in MARKETING_CURRICULUM:
        assert lesson["project"].strip()
        assert len(lesson["quiz"]) == 3
        for question in lesson["quiz"]:
            assert len(question["choices"]) == 3
            assert question["answer"] in {1, 2, 3}
            assert question["explanation"].strip()


def test_agent_receives_relevant_marketing_material_for_planning(tmp_path):
    learning = BoodaLearningManager(tmp_path / "learning.json")
    ensure_marketing_path(learning)

    class ContextPlanner:
        def __init__(self):
            self.memory = None

        def create_plan(self, goal, memory):
            self.memory = memory
            return BoodaPlan(
                goal.goal_id,
                (PlanStep("measure-results", "Measure campaign results"),),
            )

    planner = ContextPlanner()
    agent = BoodaAgent(
        planner,
        BoodaTaskManager(),
        BoodaToolRegistry(),
        BoodaExecutor(),
        learning_manager=learning,
    )
    agent.intake(BoodaGoal(
        "marketing-goal",
        "كيف أقيس نتائج الإعلانات وأحسن الحملة؟",
    ))
    agent.plan()

    materials = planner.memory["learning_materials"]
    assert materials
    assert any("قياس" in item["title"] for item in materials)
    assert all(item["origin"] == "curated_starter" for item in materials)


def test_experience_menu_enables_marketing_material_for_agent(
    tmp_path, monkeypatch, capsys
):
    audit = BoodaAuditLog(tmp_path / "audit.jsonl")
    evolution = BoodaEvolutionManager(
        tmp_path / "evolution.json",
        audit_log=audit,
    )
    learning = BoodaLearningManager(tmp_path / "learning.json")
    answers = iter(["7", "0"])
    monkeypatch.setattr(builtins, "input", lambda _prompt: next(answers))

    manage_experience_lessons(evolution, learning)

    output = capsys.readouterr().out
    assert "مواد التسويق جاهزة لسياق Booda" in output
    assert learning.get_path(MARKETING_PATH_ID) is not None


def test_course_teaches_lesson_tests_user_and_persists_progress(
    tmp_path, monkeypatch, capsys
):
    learning = BoodaLearningManager(
        tmp_path / "learning.json",
        event_log=BoodaEventLog(tmp_path / "events.jsonl"),
    )
    ensure_marketing_path(learning)
    answers = iter([
        "1",
        "اخترت أصحاب المتاجر الصغيرة، وسأسألهم عن صعوبة الوصول إلى العملاء.",
        "1", "2", "3",
    ])
    monkeypatch.setattr(builtins, "input", lambda _prompt: next(answers))

    manage_learning_course(learning)

    path = learning.get_path(MARKETING_PATH_ID)
    output = capsys.readouterr().out
    assert "الجمهور والمشكلة" in output
    assert "اجتزتِ الدرس." in output
    assert path["units"][0]["status"] == "completed"
    assert path["progress"] == 0.2
    assert path["assessments"][0]["score"] == 100
    assert path["project_submissions"][0]["unit_id"] == "audience-and-problem"
    assert "أصحاب المتاجر الصغيرة" in path["project_submissions"][0]["submission"]
    restored = BoodaLearningManager(tmp_path / "learning.json").get_path(
        MARKETING_PATH_ID
    )
    assert restored["project_submissions"] == path["project_submissions"]
    events = learning.event_log.get_events(
        entity_type="learning_path",
        entity_id=MARKETING_PATH_ID,
    )
    assert [event["event_type"] for event in events][-2:] == [
        "learning_assessment_recorded",
        "learning_unit_status_changed",
    ]
    assert any(
        event["event_type"] == "learning_project_submitted"
        for event in events
    )


def test_failed_lesson_quiz_records_score_without_falsely_completing_lesson(
    tmp_path, monkeypatch, capsys
):
    learning = BoodaLearningManager(tmp_path / "learning.json")
    ensure_marketing_path(learning)
    answers = iter(["1", "إجابة تطبيقية قصيرة", "1", "3", "1"])
    monkeypatch.setattr(builtins, "input", lambda _prompt: next(answers))

    manage_learning_course(learning)

    path = learning.get_path(MARKETING_PATH_ID)
    assert path["units"][0]["status"] == "in_progress"
    assert path["progress"] == 0
    assert path["assessments"][0]["score"] == 100 / 3
    assert "لم تجتازي الدرس بعد" in capsys.readouterr().out
