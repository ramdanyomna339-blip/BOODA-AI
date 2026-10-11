import pytest

from core.autonomy import continue_reviewed_work, execution_report
from core.brain import BoodaAgent
from core.executor import BoodaExecutor
from core.permission_manager import BoodaPermissionManager
from core.permission_policy import BoodaPermissionPolicy
from core.planning import BoodaGoal, BoodaPlan, PlanStep
from core.task_manager import BoodaTaskManager
from core.tool_registry import BoodaToolRegistry


def agent_fixture(*, verified=True, allowed=True):
    plan = BoodaPlan("g", (PlanStep("a", "قراءة", capability="read", permission_name="read"),
                           PlanStep("b", "التالي", capability="read", permission_name="read", depends_on=("a",))))
    class Planner:
        def create_plan(self, goal, memory): return plan
    class Verifier:
        def verify(self, task, result, goal): return verified
    calls = []
    registry = BoodaToolRegistry()
    registry.register("read", lambda task: calls.append(task.task_id) or "evidence")
    permissions = BoodaPermissionManager()
    permissions.add_permission("read", allowed=allowed)
    agent = BoodaAgent(Planner(), BoodaTaskManager(), registry, BoodaExecutor(),
                       permission_manager=permissions, permission_policy=BoodaPermissionPolicy(), verifier=Verifier())
    agent.intake(BoodaGoal("g", "قراءة متتابعة"))
    agent.plan()
    return agent, calls


def test_continuation_runs_dependencies_once_with_budget():
    agent, calls = agent_fixture()
    first = continue_reviewed_work(agent, max_steps=1)
    assert calls == ["a"] and not first["tools_completed"]
    final = continue_reviewed_work(agent)
    assert calls == ["a", "b"] and final["results_verified"]
    assert not final["external_objective_verified"]
    continue_reviewed_work(agent)
    assert calls == ["a", "b"]


@pytest.mark.parametrize("verified", [False, None])
def test_continuation_never_calls_unverified_result_verified(verified):
    agent, calls = agent_fixture(verified=verified)
    report = continue_reviewed_work(agent)
    assert not report["results_verified"]
    if verified is False:
        assert calls == ["a"]
        assert report["next_step"] == "inspect_failure_or_uncertainty"


def test_continuation_never_grants_or_approves():
    agent, calls = agent_fixture(allowed=False)
    assert continue_reviewed_work(agent)["phase"] == "waiting_for_permission"
    assert calls == []
    agent.state.plan_reviewed = False
    with pytest.raises(RuntimeError): continue_reviewed_work(agent)
    assert not agent.state.plan_reviewed


def test_interrupted_action_and_invalid_budget_cannot_continue():
    agent, calls = agent_fixture()
    agent.state.interrupted_task_id = "a"
    with pytest.raises(RuntimeError): continue_reviewed_work(agent)
    for budget in (True, 0, -1, 101):
        with pytest.raises(ValueError): continue_reviewed_work(agent, max_steps=budget)
    assert calls == []


def test_search_verifier_detects_fabricated_or_wrong_client_evidence(tmp_path):
    from copy import deepcopy
    from core.knowledge_base import BoodaLocalKnowledgeBase
    from core.result_verifier import BoodaArtifactVerifier
    kb = BoodaLocalKnowledgeBase(tmp_path / "kb.json")
    source = tmp_path / "source.txt"
    source.write_text("رمز العقد عقد-552", encoding="utf-8")
    kb.import_file(source, client_id="client-a")
    steps = (PlanStep("s", "بحث", capability="search_local_knowledge"),)
    tasks = BoodaTaskManager()
    task = tasks.add_task("s", "بحث")
    verifier = BoodaArtifactVerifier(lambda: steps, tasks, knowledge_base=kb)
    result = {"private": True, "sources": kb.search("رمز العقد", client_id="client-a")}
    goal = BoodaGoal("g", "بحث", {"client_id": "client-a"})
    assert verifier.verify(task, result, goal) is True
    assert verifier.verify(task, result, BoodaGoal("x", "بحث", {"client_id": "client-b"})) is False
    forged = deepcopy(result)
    forged["sources"][0]["text"] = "رمز العقد عقد-999"
    assert verifier.verify(task, forged, goal) is False
    assert verifier.verify(task, {"private": True, "sources": []}, goal) is None


def test_truncated_model_answer_is_rejected():
    from core.llm_planner import OpenAICompatiblePlanner
    planner = OpenAICompatiblePlanner(base_url="http://localhost:8080/v1", model="local",
        transport=lambda *args: {"choices": [{"finish_reason": "length", "message": {"content": "بداية ناقصة"}}]})
    with pytest.raises(ValueError, match="مبتورة"):
        planner.respond("اشرح")


@pytest.mark.parametrize("verified", [True, None])
def test_dependency_data_is_used_only_when_verified(verified):
    plan = BoodaPlan("flow", (
        PlanStep("source", "المصدر", capability="search_local_knowledge", permission_name="read"),
        PlanStep("review", "المراجعة", capability="review_output", permission_name="read", depends_on=("source",),
                 metadata={"parameters": {"observed_text": "تخمين"}, "input_bindings": {
                     "observed_text": {"task_id": "source", "path": ["sources", 0, "text"]}}}),))
    class Planner:
        def create_plan(self, goal, memory): return plan
    class Verifier:
        def verify(self, task, result, goal): return verified
    registry = BoodaToolRegistry()
    observed = []
    registry.register("search_local_knowledge", lambda task: {"sources": [{"text": "النص الفعلي عقد-821"}]})
    registry.register("review_output", lambda task: observed.append(task.metadata["parameters"]["observed_text"]) or {})
    permissions = BoodaPermissionManager()
    permissions.add_permission("read", allowed=True)
    agent = BoodaAgent(Planner(), BoodaTaskManager(), registry, BoodaExecutor(),
        permission_manager=permissions, permission_policy=BoodaPermissionPolicy(), verifier=Verifier())
    agent.intake(BoodaGoal("flow", "مراجعة نتيجة قراءة"))
    agent.plan()
    report = continue_reviewed_work(agent)
    assert observed == (["النص الفعلي عقد-821"] if verified else [])
    assert report["tools_completed"] is bool(verified)


@pytest.mark.parametrize("capability,parameter,dependency,path", [
    ("send_email", "body", "a", ["text"]),
    ("review_output", "permission", "a", ["text"]),
    ("review_output", "observed_text", "unrelated", ["text"]),
    ("review_output", "observed_text", "a", [True]),
])
def test_dataflow_rejects_unsafe_or_unrelated_bindings(capability, parameter, dependency, path):
    with pytest.raises(ValueError):
        BoodaPlan("g", (PlanStep("a", "مصدر"), PlanStep("b", "تابع", capability=capability,
            depends_on=("a",), metadata={"input_bindings": {parameter: {"task_id": dependency, "path": path}}})))


def test_replanning_remaps_dataflow_sources_without_mutating_planner_output():
    from types import SimpleNamespace
    agent, _ = agent_fixture()
    agent.task_manager.get_task("a").fail("Preparation failed before executing")
    agent.state.phase = "needs_attention"
    proposal = BoodaPlan("g", (PlanStep("new-source", "مصدر جديد", capability="search_local_knowledge"),
        PlanStep("new-review", "مراجعة جديدة", capability="review_output", depends_on=("new-source",),
            metadata={"input_bindings": {"observed_text": {"task_id": "new-source", "path": ["text"]}}})))
    agent.planner = SimpleNamespace(create_plan=lambda goal, memory: proposal)
    revised = agent.replan("استبدال الأداة الفاشلة")
    assert revised.steps[1].metadata["input_bindings"]["observed_text"]["task_id"] == revised.steps[0].task_id
    assert proposal.steps[1].metadata["input_bindings"]["observed_text"]["task_id"] == "new-source"
    assert not agent.state.plan_reviewed
