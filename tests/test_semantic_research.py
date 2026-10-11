import json

import pytest

from core.semantic_research import BoodaSemanticAnalyzer
from core.research import BoodaResearchManager
from core.brain import BoodaAgent
from core.executor import BoodaExecutor
from core.planning import BoodaGoal, BoodaPlan, PlanStep
from core.task_manager import BoodaTaskManager
from core.tool_registry import BoodaToolRegistry
from core.permission_manager import BoodaPermissionManager
from core.permission_policy import BoodaPermissionPolicy


def analyzer(rows):
    return BoodaSemanticAnalyzer(transport=lambda endpoint, payload: {
        "choices": [{"message": {"content": json.dumps({"evidence": rows})}}]})


def row(**changes):
    return dict({"source_id": "S1", "relation": "contradicts", "quote": "Conversion fell by 10%.",
                 "reason": "Decrease contradicts increase.", "confidence": .9}, **changes)


def test_semantic_contradiction_is_grounded_but_not_claimed_as_proof():
    result = analyzer([row()]).analyze("Conversion increased", [{"source_id": "S1", "text": "Conversion fell by 10%."}])
    assert result[0]["relation"] == "contradicts"
    assert result[0]["verification"] == "model_assessment_not_proof"


@pytest.mark.parametrize("item", [row(quote="Invented quotation"), row(source_id="S9"), row(confidence=2),
                                 row(confidence=float("nan")), row(relation="approve"), row(quote="")])
def test_model_cannot_fabricate_grounding_or_approve_claims(item):
    with pytest.raises(ValueError):
        analyzer([item]).analyze("claim", [{"source_id": "S1", "text": "Conversion fell by 10%."}])


def test_semantic_analyzer_rejects_remote_endpoints():
    with pytest.raises(ValueError):
        BoodaSemanticAnalyzer(base_url="https://remote.example/v1")


def setup_research(tmp_path):
    class Source:
        def search(self, *a, **k):
            return [{"source": "https://example.org/report", "title": "Experiment", "text": "Conversion fell by 10%."}]
    manager = BoodaResearchManager(tmp_path / "research.json", provider=Source())
    session = manager.research("Conversion", online=True)
    finding = manager.propose(session["id"], "Conversion increased", ["S1"], usefulness="Campaign testing")
    manager.review(session["id"], finding["id"], approve=True)
    return manager, session["id"], finding["id"]


def test_semantic_conflict_revokes_recall_until_review(tmp_path):
    manager, session, finding = setup_research(tmp_path)
    manager.semantic_compare(session, analyzer([row()]))
    assert manager.approved_knowledge("Conversion") == []
    assert manager.compare(session)[0]["state"] == "conflicting"
    with pytest.raises(ValueError):
        manager.review(session, finding, approve=True)


def test_invalid_semantic_response_does_not_modify_approved_state(tmp_path):
    manager, session, finding = setup_research(tmp_path)
    with pytest.raises(ValueError):
        manager.semantic_compare(session, analyzer([row(quote="fabrication")]))
    assert manager.approved_knowledge("Conversion")


def test_automatic_observation_uses_actual_baseline_task_results(tmp_path):
    manager, session, finding = setup_research(tmp_path)
    tasks = BoodaTaskManager()
    baseline = tasks.add_task("before", "Before")
    baseline.complete({"metrics": {"cost": 100}})
    class Planner:
        def create_plan(self, goal, memory):
            return BoodaPlan(goal.goal_id, (PlanStep("after", "Conversion test", capability="measure", permission_name="measure",
                metadata={"research_measurement": {"metric": "cost", "baseline_task_id": "before", "higher_is_better": False}}),))
    tools = BoodaToolRegistry()
    tools.register("measure", lambda task: {"metrics": {"cost": 80}})
    permissions = BoodaPermissionManager()
    permissions.add_permission("measure", allowed=True)
    agent = BoodaAgent(Planner(), tasks, tools, BoodaExecutor(), research_manager=manager,
                       permission_manager=permissions, permission_policy=BoodaPermissionPolicy())
    agent.intake(BoodaGoal("g", "Conversion"))
    agent.plan()
    assert agent.run_once().status == "completed"
    application = manager.get(session)["applications"][0]
    assert application["improved"] is True
    assert application["measurement"]["baseline_task_id"] == "before"
    assert application["evidence_type"] == "observed_task_result"
    assert application["duration_seconds"] >= 0
    manager.record_task_outcome(tasks.get_task("after"), task_manager=tasks)
    assert len(manager.get(session)["applications"]) == 1


def test_automatic_observation_keeps_unmeasured_effect_unknown(tmp_path):
    manager, session, finding = setup_research(tmp_path)
    tasks = BoodaTaskManager()
    task = tasks.add_task("t", "Conversion", metadata={"research_references": [
        {"research_id": session, "finding_id": finding, "revision": 1}],
        "research_measurement": {"metric": "cost", "baseline": 100, "higher_is_better": False}})
    task.complete({"metrics": {"cost": 80}})
    application = manager.record_task_outcome(task, task_manager=tasks)[0]
    assert application["improved"] is None and application["measurement"] is None
