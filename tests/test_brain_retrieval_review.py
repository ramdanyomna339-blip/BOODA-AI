from core.brain import BoodaAgent
from core.executor import BoodaExecutor
from core.file_action import save_task_content, save_plan_artifact
from core.memory import BoodaStructuredMemoryStore
from core.planning import BoodaGoal, BoodaPlan, PlanStep
from core.permission_manager import BoodaPermissionManager
from core.permission_policy import BoodaPermissionPolicy
from core.result_verifier import BoodaArtifactVerifier
from core.task_manager import BoodaTaskManager
from core.tool_registry import BoodaToolRegistry


def test_conversation_retrieves_new_topic_from_all_sources_without_changing_goal(tmp_path):
    memory = BoodaStructuredMemoryStore(tmp_path / "memory.sqlite3")
    memory.add_confirmed("fact", "ميزانية", "ميزانية العميل 7000", rationale="fixture",
                         user_confirmed=True)
    calls = []
    class Source:
        def search(self, query, **kwargs):
            calls.append(("documents", query))
            return []
        def approved_knowledge(self, query, **kwargs):
            calls.append(("research", query))
            return []
        def recall_experience_lessons(self, query, **kwargs):
            calls.append(("lessons", query))
            return []
    class Planner:
        def respond(self, message, *, context, memory):
            assert memory["structured_memory"]["approved_memory"]["fact"]
            assert context["goal"]["intent"] == "تصميم عبوة"
            return "رد"
    source = Source()
    agent = BoodaAgent(Planner(), BoodaTaskManager(), BoodaToolRegistry(), BoodaExecutor(),
                       structured_memory=memory, knowledge_base=source,
                       research_manager=source, evolution_manager=source)
    agent.intake(BoodaGoal("g", "تصميم عبوة"))
    assert agent.respond("ميزانية العميل") == "رد"
    assert calls == [("lessons", "ميزانية العميل"), ("documents", "ميزانية العميل"),
                     ("research", "ميزانية العميل")]
    assert agent.state.goal.intent == "تصميم عبوة"


def test_relevant_old_fact_survives_recent_irrelevant_records(tmp_path):
    memory = BoodaStructuredMemoryStore(tmp_path / "memory.sqlite3")
    memory.add_confirmed("fact", "ميزانية", "ميزانية العميل 7000", rationale="fixture",
                         user_confirmed=True)
    for index in range(35):
        memory.add_confirmed("fact", f"noise{index}", "unrelated", rationale="fixture",
                             user_confirmed=True)
    result = memory.recall_context(BoodaGoal("g", "ميزانية"), limit=2)
    assert result["approved_memory"]["fact"][0]["memory_key"] == "ميزانية"


def test_verifier_checks_draft_contents_and_rejects_missing_or_external_file(tmp_path):
    tasks = BoodaTaskManager()
    task = tasks.add_task("t", "عنوان", description="محتوى عربي")
    step = PlanStep("t", "عنوان", capability="save_task_content")
    root = tmp_path / "outputs"
    verifier = BoodaArtifactVerifier(lambda: (step,), tasks, root)
    path = save_task_content(task, root)
    goal = BoodaGoal("g", "اكتب")
    assert verifier.verify(task, path, goal) is True
    from pathlib import Path
    Path(path).write_text("wrong", encoding="utf-8")
    assert verifier.verify(task, path, goal) is False
    assert verifier.verify(task, tmp_path / "outside.txt", goal) is False
    Path(path).unlink()
    assert verifier.verify(task, path, goal) is False


def test_plan_artifact_is_verified_as_plan_not_completed_user_goal(tmp_path):
    tasks = BoodaTaskManager()
    task = tasks.add_task("t", "بحث", description="راجع المصادر")
    steps = (PlanStep("t", "بحث", capability="create_plan_artifact"),)
    verifier = BoodaArtifactVerifier(lambda: steps, tasks, tmp_path)
    goal = BoodaGoal("g", "بحث")
    path = save_plan_artifact("g", "بحث", [task], tmp_path)
    assert verifier.verify(task, path, goal) is True
    assert verifier.verify(task, path, BoodaGoal("other", "بحث")) is False


def test_verifier_exception_stops_dependencies_as_uncertain():
    class Planner:
        def create_plan(self, goal, memory):
            return BoodaPlan("g", (PlanStep("a", "A", capability="write", permission_name="write"),
                                  PlanStep("b", "B", capability="write", permission_name="write", depends_on=("a",))))
    class Verifier:
        def verify(self, *args):
            raise OSError("unreadable")
    registry = BoodaToolRegistry()
    executed = []
    registry.register("write", lambda task: executed.append(task.task_id) or "result")
    permissions = BoodaPermissionManager()
    permissions.add_permission("write", allowed=True)
    agent = BoodaAgent(Planner(), BoodaTaskManager(), registry, BoodaExecutor(), verifier=Verifier(),
                       permission_manager=permissions, permission_policy=BoodaPermissionPolicy())
    agent.intake(BoodaGoal("g", "write"))
    agent.plan()
    agent.run_until_blocked()
    assert executed == ["a"]
    assert agent.task_manager.get_task("a").status == "uncertain"
    assert agent.task_manager.get_task("a").result["action_result"] == "result"
    assert agent.task_manager.get_task("b").status == "pending"
    assert agent.state.phase == "needs_attention"
