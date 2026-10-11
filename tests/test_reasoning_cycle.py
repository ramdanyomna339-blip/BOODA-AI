import json
from types import SimpleNamespace

import pytest

from core.brain import BoodaAgent
from core.capability_registry import BoodaCapabilityRegistry
from core.executor import BoodaExecutor
from core.knowledge_base import BoodaLocalKnowledgeBase
from core.llm_planner import OpenAICompatiblePlanner
from core.permission_manager import BoodaPermissionManager
from core.permission_policy import BoodaPermissionPolicy
from core.planning import BoodaGoal, BoodaPlan, PlanStep
from core.reasoning_tools import register_reasoning_tools
from core.task import BoodaTask
from core.task_manager import BoodaTaskManager
from core.tool_registry import BoodaToolRegistry


def test_explicit_local_tool_request_has_single_step_schema():
    requests = []
    def transport(endpoint, payload):
        requests.append(payload)
        return {"choices": [{"message": {"content": json.dumps({"plan_id": "p", "steps": [{
            "task_id": "lookup", "title": "بحث", "description": "بحث المرجع",
            "capability": "search_local_knowledge", "permission_name": "knowledge_read",
            "depends_on": [], "metadata": {"parameters": {"query": "عميل"}},
        }]})}}]}
    planner = OpenAICompatiblePlanner(base_url="http://127.0.0.1:8080/v1", model="test",
        transport=transport, capability_permissions={"search_local_knowledge": ("knowledge_read",),
                                                    "review_output": ("output_review",)})
    planner.capability_names = ["search_local_knowledge", "review_output"]
    planner.permission_names = ["knowledge_read", "output_review"]
    planner.create_plan(BoodaGoal("g", "استخدم search_local_knowledge للبحث عن عميل"), {})
    steps = requests[0]["response_format"]["json_schema"]["schema"]["properties"]["steps"]
    assert steps["maxItems"] == 1
    assert len(steps["items"]["anyOf"]) == 1
    assert steps["items"]["anyOf"][0]["properties"]["capability"]["const"] == "search_local_knowledge"


def test_review_rejects_model_replacement_of_explicit_user_text():
    def transport(endpoint, payload):
        const = payload["response_format"]["json_schema"]["schema"]["properties"]["steps"]["items"]["anyOf"][0]["properties"]["metadata"]["properties"]["parameters"]["const"]
        assert const["required_text"] == ["عنوان", "كود-99"]
        wrong = dict(const, required_text=["نسخة مخترعة"])
        return {"choices": [{"message": {"content": json.dumps({"plan_id": "p", "steps": [{
            "task_id": "review", "title": "مراجعة", "description": "راجع الملاحظات",
            "capability": "review_output", "permission_name": "output_review", "depends_on": [],
            "metadata": {"parameters": wrong}}]})}}]}
    planner = OpenAICompatiblePlanner(base_url="http://127.0.0.1:8080/v1", model="test",
        transport=transport, capability_permissions={"review_output": ("output_review",)})
    planner.capability_names = ["review_output"]
    planner.permission_names = ["output_review"]
    with pytest.raises(ValueError, match="explicit user observations"):
        planner.create_plan(BoodaGoal("g", "review_output: المقاس المطلوب 720×720. "
            "المقاس الملاحظ 800×720. النصوص المطلوبة عنوان وكود-99. النص الملاحظ عنوان فقط."), {})


def test_local_planner_can_search_then_answer_from_actual_tool_result(tmp_path):
    path = tmp_path / "reference.md"
    path.write_text("اسم المتجر As Store وليس ACS.", encoding="utf-8")
    kb = BoodaLocalKnowledgeBase(tmp_path / "documents.json")
    kb.import_file(path, private=True, reference_status="unverified_historical")
    manifest = BoodaCapabilityRegistry(tmp_path / "capabilities.json")
    permissions = BoodaPermissionManager()
    registry = BoodaToolRegistry(manifest)
    mapping = register_reasoning_tools(registry, manifest, permissions,
                                      knowledge_base=kb, ad_intelligence=None)
    received = []
    def transport(endpoint, payload):
        content = payload["messages"][1]["content"]
        if "\n\nبيانات مرجعية فقط:\n" in content:
            message, reference = content.split("\n\nبيانات مرجعية فقط:\n", 1)
            user = {"message": message, **json.loads(reference)}
        else:
            user = json.loads(content)
        received.append(user)
        if "goal" in user:
            assert "metadata.parameters" in user["capability_descriptions"]["search_local_knowledge"]
            answer = json.dumps({"plan_id": "p", "steps": [{
                "task_id": "lookup", "title": "ابحث عن اسم المتجر", "description": "استرجع المرجع",
                "capability": "search_local_knowledge", "permission_name": "knowledge_read",
                "depends_on": [], "metadata": {"parameters": {"query": "As Store"}},
            }]})
        else:
            result = user["context"]["tasks"][0]["result"]
            assert result["private"]
            assert "As Store" in result["sources"][0]["text"]
            answer = "المرجع التاريخي بيذكر As Store؛ محتاج تأكيد إنه الاسم الحالي."
        return {"choices": [{"message": {"content": answer}}]}
    planner = OpenAICompatiblePlanner(base_url="http://127.0.0.1:8080/v1", model="test",
                                      transport=transport, capability_permissions=mapping)
    agent = BoodaAgent(planner, BoodaTaskManager(), registry, BoodaExecutor(),
                       permission_manager=permissions, permission_policy=BoodaPermissionPolicy())
    agent.intake(BoodaGoal("g", "اسم المتجر إيه؟"))
    plan = agent.plan()
    agent.approve_plan(plan.plan_id)
    assert agent.run_once()["status"] == "waiting_for_permission"
    permissions.grant_permission("knowledge_read")
    assert agent.run_once().status == "completed"
    assert "تأكيد" in agent.respond("لقيت إيه؟")
    assert len(received) == 2


def test_remote_payload_redacts_private_results_and_nested_replanning_memory():
    remote = OpenAICompatiblePlanner(base_url="https://example.com/v1", model="test")
    payload = {"tasks": [{"result": {"private": True, "snapshot": "SENSITIVE"}}],
               "memory": {"structured_memory": {"secret_fact": "SENSITIVE"},
                          "local_sources": [{"private": True, "text": "SENSITIVE"}]}}
    safe = remote._memory_for_planner(payload)
    assert "SENSITIVE" not in json.dumps(safe)
    assert payload["tasks"][0]["result"]["snapshot"] == "SENSITIVE"


def test_new_goal_resets_recovery_state():
    agent = BoodaAgent(None, BoodaTaskManager(), BoodaToolRegistry(), BoodaExecutor())
    agent.state.phase = "completed"
    agent.state.replan_count = 3
    agent.state.interrupted_task_id = "old"
    agent.state.plan_reviewed = True
    agent.intake(BoodaGoal("new", "هدف جديد"))
    assert agent.state.replan_count == 0
    assert agent.state.interrupted_task_id is None
    assert agent.state.plan_reviewed is False


def test_existing_plan_cannot_be_replaced_by_calling_plan_again():
    agent = BoodaAgent(None, BoodaTaskManager(), BoodaToolRegistry(), BoodaExecutor())
    agent.intake(BoodaGoal("g", "goal"))
    agent.state.plan = BoodaPlan("g", (PlanStep("t", "task"),))
    with pytest.raises(RuntimeError, match="already exists"):
        agent.plan()


def test_uncertain_action_cannot_be_repeated_under_a_different_title():
    planner = SimpleNamespace(create_plan=lambda *args: BoodaPlan("g", (
        PlanStep("new", "Different title", capability="send"),)))
    tasks = BoodaTaskManager()
    task = tasks.add_task("old", "Original title")
    task.mark_uncertain("may have sent")
    agent = BoodaAgent(planner, tasks, BoodaToolRegistry(), BoodaExecutor())
    agent.intake(BoodaGoal("g", "goal"))
    agent.state.plan = BoodaPlan("g", (PlanStep("old", "Original title", capability="send"),))
    agent._steps = {step.task_id: step for step in agent.state.plan.steps}
    agent.state.phase = "needs_attention"
    with pytest.raises(ValueError, match="uncertain action"):
        agent.replan("try again")
    assert tasks.get_task("new") is None


def test_missing_task_does_not_crash_phase_update():
    agent = BoodaAgent(None, BoodaTaskManager(), BoodaToolRegistry(), BoodaExecutor())
    agent.intake(BoodaGoal("g", "goal"))
    agent.state.plan = BoodaPlan("g", (PlanStep("missing", "task"),))
    agent._update_phase()
    assert agent.state.phase == "needs_attention"


def test_reasoning_tools_reject_malformed_parameters_and_missing_campaign(tmp_path):
    manifest = BoodaCapabilityRegistry(tmp_path / "manifest.json")
    permissions = BoodaPermissionManager()
    registry = BoodaToolRegistry(manifest)
    register_reasoning_tools(registry, manifest, permissions, knowledge_base=None,
                             ad_intelligence=SimpleNamespace(get_snapshot=lambda _: None))
    action = registry.require("read_campaign_snapshot")
    with pytest.raises(ValueError, match="exactly"):
        action(BoodaTask("t", "t", metadata={"parameters": {"snapshot_id": "x", "write": True}}))
    with pytest.raises(ValueError, match="not found"):
        action(BoodaTask("t", "t", metadata={"parameters": {"snapshot_id": "x"}}))
    with pytest.raises(ValueError, match="not found"):
        action(BoodaTask("t", "t", metadata={"snapshot_id": "x", "research_references": []}))
    with pytest.raises(ValueError, match="exactly"):
        action(BoodaTask("t", "t", metadata={"snapshot_id": "x", "write": True}))


def test_manifest_permissions_are_derived_and_disabled_tools_are_not_offered(tmp_path):
    manifest = BoodaCapabilityRegistry(tmp_path / "manifest.json")
    manifest.register("read", permission_name="read_permission")
    registry = BoodaToolRegistry(manifest)
    registry.register("read", lambda _: "read")
    permissions = BoodaPermissionManager()
    permissions.add_permission("read_permission")
    planner = OpenAICompatiblePlanner(base_url="http://127.0.0.1:8080/v1", model="test")
    planner.configure_agent(registry=registry, permission_manager=permissions)
    assert planner.capability_permissions == {"read": ("read_permission",)}
    manifest.set_enabled("read", False)
    planner.configure_agent(registry=registry, permission_manager=permissions)
    assert planner.capability_names == []


def test_nonobject_model_response_reports_validation_error():
    planner = OpenAICompatiblePlanner(base_url="http://127.0.0.1:8080/v1", model="test",
        transport=lambda *args: {"choices": [{"message": {"content": "[]"}}]})
    with pytest.raises(ValueError, match="JSON object"):
        planner.create_plan(BoodaGoal("g", "goal"), {})


def test_reimport_can_tighten_evidence_status_but_not_promote_it(tmp_path):
    path = tmp_path / "reference.md"
    path.write_text("historical information", encoding="utf-8")
    kb = BoodaLocalKnowledgeBase(tmp_path / "documents.json")
    first = kb.import_file(path)
    second = kb.import_file(path, private=True, reference_status="unverified_historical")
    assert first["document_id"] == second["document_id"]
    assert second["private"] is True
    assert kb.import_file(path, reference_status="reviewed_lesson")["reference_status"] == "unverified_historical"
