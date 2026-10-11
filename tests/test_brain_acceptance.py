from types import SimpleNamespace

import pytest

from core.agent_session import BoodaAgentSessionStore
from core.brain import BoodaAgent
from core.executor import BoodaExecutor
from core.knowledge_base import BoodaLocalKnowledgeBase
from core.memory import BoodaStructuredMemoryStore
from core.planning import BoodaGoal
from core.task_manager import BoodaTaskManager
from core.tool_registry import BoodaToolRegistry
from core.conversation_checks import checked_answer, checked_execution_claim
from core.conversation_checks import literal_fields


def agent_for(planner, **kwargs):
    return BoodaAgent(planner, BoodaTaskManager(), BoodaToolRegistry(), BoodaExecutor(), **kwargs)


def test_arithmetic_failure_is_not_presented_as_an_accepted_answer():
    answer = checked_answer("اللون أزرق. ١٥٪ من ٢٠٠٠ = ٣٠. تم اعتماد النتيجة.")
    assert "300" in answer and "لم أعتمده" in answer
    assert "تم اعتماد النتيجة" not in answer
    assert checked_answer("25% من 7000 = 1750") == "25% من 7000 = 1750"
    assert "لم أعتمده" in checked_answer("25% من الميزانية (7000) = 175")
    assert "لم أعتمده" in checked_answer("25% من 7000 = 1750، ثم 25% من 7000 = 175")


def test_execution_claim_requires_matching_completed_verified_action():
    assert "لم أعتمده" in checked_execution_claim("تم نشر الإعلان", [])
    assert "لم أعتمده" in checked_execution_claim("تم حفظ المسودة", [{"capability": "save_task_content", "status": "completed", "verification": "unavailable"}])
    evidence = [{"capability": "save_task_content", "status": "completed", "verification": "passed"}]
    assert checked_execution_claim("تم حفظ المسودة", evidence) == "تم حفظ المسودة"
    assert "لم أعتمده" in checked_execution_claim("تم نشر الإعلان", evidence)


def test_conversation_survives_restart_and_is_cleared_for_a_new_goal(tmp_path):
    store = BoodaAgentSessionStore(tmp_path / "sessions.json")
    def respond(message, *, context, memory):
        if message == "كمل":
            assert context["conversation_history"]["turns"][0]["message"] == "خلّي اللون أزرق"
        return "تمام"
    planner = SimpleNamespace(respond=respond)
    first = agent_for(planner, session_store=store)
    first.intake(BoodaGoal("a", "تصميم", {"client_id": "a"}))
    first.respond("خلّي اللون أزرق")
    second = agent_for(planner, session_store=store)
    second.respond("كمل")
    assert len(second.state.conversation) == 2
    second.intake(BoodaGoal("b", "تصميم", {"client_id": "b"}), replace_current=True)
    assert second.state.conversation == []


def test_secret_in_conversation_is_not_persisted(tmp_path):
    store = BoodaAgentSessionStore(tmp_path / "sessions.json")
    agent = agent_for(SimpleNamespace(respond=lambda *a, **k: "لن أحفظ المفتاح"), session_store=store)
    agent.intake(BoodaGoal("a", "مراجعة"))
    agent.respond("api_key=privateCredential123456")
    assert agent.state.conversation == []
    assert "privateCredential123456" not in (tmp_path / "sessions.json").read_text(encoding="utf-8")


def test_correction_requires_confirmation_and_is_scoped_to_client(tmp_path):
    store = BoodaStructuredMemoryStore(tmp_path / "memory.sqlite3")
    agent = agent_for(SimpleNamespace(), structured_memory=store)
    agent.intake(BoodaGoal("a", "لون الهوية", {"client_id": "a"}))
    with pytest.raises(PermissionError):
        agent.record_user_correction("لون الهوية أحمر", "لون الهوية أزرق", "تأكيد العميل")
    entry = agent.record_user_correction("لون الهوية أحمر", "لون الهوية أزرق", "تأكيد العميل", user_confirmed=True)
    recalled = store.recall_context(BoodaGoal("a2", "لون الهوية", {"client_id": "a"}))
    assert recalled["approved_memory"]["lesson"][0]["entry_id"] == entry["entry_id"]
    other = store.recall_context(BoodaGoal("b", "لون الهوية", {"client_id": "b"}))
    assert other["approved_memory"] == {}


def test_private_conversation_is_excluded_from_remote_context(tmp_path):
    from core.llm_planner import OpenAICompatiblePlanner
    remote = OpenAICompatiblePlanner(base_url="https://example.com/v1", model="test")
    context = {"conversation_history": {"private": True, "turns": [{"answer": "CLIENT_SECRET"}]}}
    assert "CLIENT_SECRET" not in str(remote._memory_for_planner(context))


def test_document_scope_does_not_leak_between_clients_or_deduplicate_them(tmp_path):
    source = tmp_path / "client.txt"
    source.write_text("رمز المشروع كود-913", encoding="utf-8")
    kb = BoodaLocalKnowledgeBase(tmp_path / "documents.json")
    a = kb.import_file(source, private=True, client_id="a")
    b = kb.import_file(source, private=True, client_id="b")
    assert a["document_id"] != b["document_id"]
    assert kb.search("رمز المشروع") == []
    assert {item["client_id"] for item in kb.search("رمز المشروع", client_id="a")} == {"a"}
    assert kb.search("رمز المشروع", client_id="c") == []


def test_capability_inventory_respects_planner_allowlist_and_live_disable(tmp_path):
    from core.capability_registry import BoodaCapabilityRegistry
    manifest = BoodaCapabilityRegistry(tmp_path / "caps.json")
    manifest.register("read", permission_name="read")
    manifest.register("write", permission_name="write")
    registry = BoodaToolRegistry(manifest)
    registry.register("read", lambda task: "ok")
    registry.register("write", lambda task: "ok")
    agent = BoodaAgent(SimpleNamespace(capability_names=["read"]), BoodaTaskManager(), registry, BoodaExecutor())
    assert [item["name"] for item in agent.available_capabilities()] == ["read"]
    manifest.set_enabled("read", False)
    assert agent.available_capabilities() == []


def test_literal_field_retrieval_generalizes_and_keeps_source_uncertainty():
    sources = [{"title": "catalog", "text": "اسم المنتج سيروم، سعر العبوة 120.5.",
                "reference_status": "unverified_historical"}]
    answer = literal_fields("اذكر اسم المنتج وسعر العبوة فقط", sources)
    assert "اسم المنتج: سيروم" in answer and "سعر العبوة: 120.5" in answer
    assert "catalog" in answer and "تاريخي غير مؤكد" in answer
    conflicting = sources + [{"title": "other", "text": "اسم المنتج كريم، سعر العبوة 120.5."}]
    assert "متعارضة" in literal_fields("اذكر اسم المنتج فقط", conflicting)
    assert literal_fields("اذكر تاريخ التأسيس فقط", sources) is None


def test_registered_state_answer_does_not_invent_execution():
    def must_not_generate(*args, **kwargs):
        raise AssertionError("State facts should not be guessed by a model")
    agent = agent_for(SimpleNamespace(respond=must_not_generate))
    agent.intake(BoodaGoal("g", "احفظ خطة"))
    answer = agent.respond("وصلنا لفين؟")
    assert "received" in answer and "لا توجد خطة" in answer


def test_knowledge_tool_cannot_change_client_using_model_metadata(tmp_path):
    from core.capability_registry import BoodaCapabilityRegistry
    from core.permission_manager import BoodaPermissionManager
    from core.reasoning_tools import register_reasoning_tools
    from core.task import BoodaTask
    source = tmp_path / "source.txt"
    source.write_text("رمز المشروع كود-913", encoding="utf-8")
    kb = BoodaLocalKnowledgeBase(tmp_path / "documents.json")
    kb.import_file(source, client_id="other")
    manifest = BoodaCapabilityRegistry(tmp_path / "caps.json")
    registry = BoodaToolRegistry(manifest)
    register_reasoning_tools(registry, manifest, BoodaPermissionManager(), knowledge_base=kb,
        ad_intelligence=None, scope_provider=lambda: {"client_id": "current"})
    task = BoodaTask("t", "بحث", metadata={"parameters": {"query": "رمز المشروع"}, "client_id": "other"})
    assert registry.require("search_local_knowledge")(task)["sources"] == []


def test_artifact_integrity_is_not_enough_when_user_requirements_are_missing(tmp_path):
    from core.file_action import save_task_content
    from core.result_verifier import BoodaArtifactVerifier
    from core.planning import PlanStep
    tasks = BoodaTaskManager()
    task = tasks.add_task("t", "مسودة", description="عنوان فقط")
    step = PlanStep("t", "مسودة", capability="save_task_content")
    destination = tmp_path / "outputs"
    path = save_task_content(task, destination)
    verifier = BoodaArtifactVerifier(lambda: (step,), tasks, destination)
    assert verifier.verify(task, path, BoodaGoal("g", "مسودة")) is True
    assert verifier.verify(task, path, BoodaGoal("g", "مسودة", {"acceptance": {"required_text": ["وسيلة التواصل"]}})) is False
    assert verifier.verify(task, path, BoodaGoal("g", "مسودة", {"acceptance": {"forbidden_text": ["عنوان فقط"]}})) is False
def test_decimal_calculator_does_not_guess_or_execute_code():
    from core.calculator import calculate_request
    assert calculate_request("احسب ٢٥٪ من ٧٠٠٠") == "نتيجة الحساب: 1750"
    assert calculate_request("احسب 0.1 + 0.2") == "نتيجة الحساب: 0.3"
    assert calculate_request("احسب (12-2) × 3") == "نتيجة الحساب: 30"
    assert "لم أخمّن" in calculate_request("احسب 1/0")
    assert "لم أخمّن" in calculate_request("احسب 2**3")
    assert "لم أنفذ" in calculate_request("احسب __import__('os')")
    assert calculate_request("صباح الخير") is None


