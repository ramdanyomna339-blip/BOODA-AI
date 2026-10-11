from datetime import datetime, timezone
import json

import pytest

from core.audit_log import BoodaAuditLog
from core.brain import BoodaAgent
from core.evolution_manager import BoodaEvolutionManager
from core.executor import BoodaExecutor
from core.llm_planner import OpenAICompatiblePlanner
from core.planning import BoodaGoal, BoodaPlan, PlanStep
from core.research import BoodaResearchManager, source_freshness
from core.task_manager import BoodaTaskManager
from core.tool_registry import BoodaToolRegistry


class Sources:
    def search(self, query, **kwargs):
        return [{"title": "Study", "source": "https://one.example/study", "publisher": "one.example",
                 "text": "Marketing improves through controlled experiments. Results need measurement.",
                 "updated_at": "2020-01-01T00:00:00Z"},
                {"title": "Counterexample", "source": "https://two.example/study", "publisher": "two.example",
                 "text": "Marketing experiments can fail without enough observations."}]


@pytest.fixture
def workflow(tmp_path):
    manager = BoodaResearchManager(tmp_path / "research.json", provider=Sources(), output_dir=tmp_path / "reports")
    session = manager.research("Marketing experiments", online=True)
    finding = manager.propose(session["id"], "Marketing improves through controlled experiments.",
                              ["S1"], usefulness="Test campaign variants")
    return manager, session["id"], finding["id"]


def test_evidence_validation_conflict_blocks_approval_and_resolution_requires_review(workflow):
    manager, session, finding = workflow
    manager.review(session, finding, approve=True)
    with pytest.raises(ValueError):
        manager.add_evidence(session, finding, "S2", "a fabricated quotation", relation="contradicts")
    assert manager.get(session)["findings"][0]["status"] == "approved"
    manager.add_evidence(session, finding, "S2", "can fail", relation="contradicts")
    assert manager.compare(session)[0]["state"] == "conflicting"
    assert manager.approved_knowledge("Marketing") == []
    with pytest.raises(ValueError):
        manager.review(session, finding, approve=True)
    manager.remove_evidence(session, finding, 0)
    assert manager.compare(session)[0]["state"] == "single_publisher_support"
    assert manager.approved_knowledge("Marketing") == []
    manager.review(session, finding, approve=True)
    assert manager.approved_knowledge("Marketing")


def test_correction_invalidates_approval_and_retains_history(workflow):
    manager, session, finding = workflow
    manager.review(session, finding, approve=True)
    manager.correct_finding(session, finding, statement="Marketing needs testing.", usefulness="Plan a test")
    assert manager.approved_knowledge("Marketing") == []
    record = manager.get(session)["findings"][0]
    assert record["history"][-1]["previous_statement"].startswith("Marketing improves")
    assert record["evidence"] == []


def test_extraction_is_verbatim_pending_and_idempotent(workflow):
    manager, session, _ = workflow
    candidates = manager.extract_candidates(session)
    sources = {s["source_id"]: s for s in manager.get(session)["sources"]}
    assert candidates
    for finding in candidates:
        assert finding["status"] == "pending"
        assert finding["statement"] in sources[finding["source_ids"][0]]["text"]
    assert manager.extract_candidates(session) == []


def test_measurements_use_correct_direction_and_preserve_unknowns(workflow):
    manager, session, finding = workflow
    manager.review(session, finding, approve=True)
    measured = manager.record_application(session, finding, task_id="t1", observation="Measured cost per lead",
        metric="EGP per lead", baseline=100, result=80, higher_is_better=False)
    assert measured["improved"] is True and measured["measurement"]["delta"] == -20
    manager.record_application(session, finding, task_id="t2", observation="No metric available")
    summary = manager.learning_summary(session)
    assert (summary["improved"], summary["unknown"], summary["measured"]) == (1, 1, 1)
    for baseline in [float("nan"), float("inf"), True]:
        with pytest.raises(ValueError):
            manager.record_application(session, finding, task_id="t3", observation="Invalid",
                metric="count", baseline=baseline, result=1)
    with pytest.raises(ValueError):
        manager.record_application(session, finding, task_id="t4", observation="Contradictory",
            metric="count", baseline=10, result=1, improved=True)


def test_evolution_bridge_is_review_only_idempotent_and_traceable(workflow, tmp_path):
    manager, session, finding = workflow
    evolution = BoodaEvolutionManager(tmp_path / "evolution.json", audit_log=BoodaAuditLog(tmp_path / "audit.jsonl"))
    with pytest.raises(ValueError):
        manager.propose_improvement(session, finding, evolution_manager=evolution)
    manager.review(session, finding, approve=True)
    manager.record_application(session, finding, task_id="t1", observation="A recorded outcome")
    first = manager.propose_improvement(session, finding, evolution_manager=evolution)
    second = manager.propose_improvement(session, finding, evolution_manager=evolution)
    assert first["proposal_id"] == second["proposal_id"]
    assert first["status"] == "proposed"
    assert session in first["proposed_solution"]
    assert "t1" in first["problem"]
    manager.correct_finding(session, finding, statement="Marketing requires a larger sample.", usefulness="A new hypothesis")
    manager.review(session, finding, approve=True)
    # Previous observations describe revision 1, not the newly corrected claim.
    with pytest.raises(ValueError):
        manager.propose_improvement(session, finding, evolution_manager=evolution)
    manager.record_application(session, finding, task_id="t2", observation="New revision tested")
    revised = manager.propose_improvement(session, finding, evolution_manager=evolution)
    assert revised["proposal_id"] != first["proposal_id"]
    assert "t2" in revised["problem"] and "t1" not in revised["problem"]
    assert "history" not in manager.approved_knowledge("Marketing")[0]


def test_separate_managers_do_not_overwrite_each_others_changes(workflow):
    first, session, finding = workflow
    second = BoodaResearchManager(first.store.file_path, provider=Sources())
    second.research("another topic")
    first.review(session, finding, approve=True)
    assert len(second.list_sessions()) == 2
    assert second.approved_knowledge("Marketing")


def test_report_and_recall_removed_on_delete(workflow):
    manager, session, finding = workflow
    manager.review(session, finding, approve=True)
    path = manager.export_report(session)
    assert path.exists()
    manager.delete_session(session)
    assert not path.exists() and manager.approved_knowledge("Marketing") == []


def test_freshness_is_revision_age_not_truth():
    date = datetime(2026, 10, 10, tzinfo=timezone.utc)
    assert source_freshness({}, at=date) == "unknown"
    assert source_freshness({"updated_at": "invalid"}, at=date) == "unknown"
    assert source_freshness({"updated_at": "2020-01-01T00:00:00Z"}, at=date) == "review_age"
    assert source_freshness({"updated_at": "Fri, 09 Oct 2026 10:00:00 GMT"}, at=date) == "recent_revision"
    assert source_freshness({"updated_at": "2030-01-01T00:00:00Z"}, at=date) == "unknown"


def test_agent_retrieves_only_approved_relevant_research_for_plans_and_chat(workflow):
    manager, session, finding = workflow

    class Planner:
        def create_plan(self, goal, memory):
            self.memory = memory
            return BoodaPlan(goal.goal_id, (PlanStep("t", "Draft"),))

        def respond(self, message, *, context, memory):
            self.memory = memory
            return "Answer"

    planner = Planner()
    agent = BoodaAgent(planner, BoodaTaskManager(), BoodaToolRegistry(), BoodaExecutor(), research_manager=manager)
    agent.intake(BoodaGoal("g", "Marketing"))
    agent.plan()
    assert planner.memory["research_knowledge"] == []
    manager.review(session, finding, approve=True)
    agent.respond("Marketing experiments")
    assert planner.memory["research_knowledge"][0]["id"] == finding
    assert planner.memory["research_knowledge"][0]["sources"][0]["freshness"] == "review_age"
    agent.respond("quantum")
    assert planner.memory["research_knowledge"] == []


def test_remote_privacy_flags_are_independent():
    memory = {"structured_memory": {"private": "a"}, "research_knowledge": [{"private": "b"}], "other": 1}
    for share_structured in [False, True]:
        for share_research in [False, True]:
            planner = OpenAICompatiblePlanner(base_url="https://example.test/v1", model="test",
                share_structured_memory=share_structured, share_research_memory=share_research)
            sent = planner._memory_for_planner(memory)
            assert ("structured_memory" in sent) == share_structured
            assert ("research_knowledge" in sent) == share_research
    local = OpenAICompatiblePlanner(base_url="http://127.0.0.1:1234/v1", model="test")
    assert local._memory_for_planner(memory) == memory
    assert memory["research_knowledge"]


def test_research_needs_identify_missing_knowledge_and_failed_tasks(workflow):
    manager, session, finding = workflow
    tasks = BoodaTaskManager()
    task = tasks.add_task("failed-marketing", "Marketing campaign")
    task.fail("No evidence available")
    needs = manager.research_needs("Marketing", task_manager=tasks)
    reasons = {n["reason"] for n in needs["needs"]}
    assert "no_approved_relevant_knowledge" in reasons
    assert "task_outcome_needs_investigation" in reasons
    manager.review(session, finding, approve=True)
    reasons = {n["reason"] for n in manager.research_needs("Marketing")["needs"]}
    assert "source_age_needs_review" in reasons
    assert "no_approved_relevant_knowledge" not in reasons


def test_research_knowledge_is_filtered_in_real_remote_payload():
    payloads = []
    def transport(endpoint, payload):
        payloads.append(payload)
        return {"choices": [{"message": {"content": "Answer"}}]}
    planner = OpenAICompatiblePlanner(base_url="https://example.test/v1", model="test", transport=transport)
    planner.respond("hello", memory={"research_knowledge": [{"statement": "PRIVATE_FINDING"}]})
    assert "PRIVATE_FINDING" not in json.dumps(payloads)


def test_local_plan_format_cannot_bypass_remote_research_privacy():
    payloads = []
    def transport(endpoint, payload):
        payloads.append(payload)
        raise RuntimeError("captured request")
    planner = OpenAICompatiblePlanner(base_url="https://example.test/v1", model="test",
        transport=transport, local_planning=True)
    with pytest.raises(RuntimeError, match="captured request"):
        planner._create_plan(BoodaGoal("g", "learn programming"),
                             {"research_knowledge": [{"statement": "PRIVATE_FINDING"}]})
    assert payloads and "PRIVATE_FINDING" not in json.dumps(payloads)
