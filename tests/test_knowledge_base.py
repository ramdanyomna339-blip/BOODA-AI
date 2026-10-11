import builtins
import json

import pytest

from core.brain import BoodaAgent
from core.event_log import BoodaEventLog
from core.executor import BoodaExecutor
from core.knowledge_base import BoodaLocalKnowledgeBase
from core.llm_planner import OpenAICompatiblePlanner
from core.main import manage_local_knowledge_base
from core.planning import BoodaGoal, BoodaPlan, PlanStep
from core.permission_manager import BoodaPermissionManager
from core.task_manager import BoodaTaskManager
from core.tool_registry import BoodaToolRegistry
from core.versioning import BoodaVersionStore


def test_import_search_persists_utf8_markdown_and_source(tmp_path):
    source_path = tmp_path / "marketing.md"
    source_path.write_text(
        "# تحليل الحملة\n"
        "قيسي تكلفة الاستفسارات المؤهلة بدل الاعتماد على المشاهدات فقط.\n",
        encoding="utf-8",
    )
    events = BoodaEventLog(tmp_path / "events.jsonl")
    versions = BoodaVersionStore(tmp_path / "versions.jsonl")
    manager = BoodaLocalKnowledgeBase(
        tmp_path / "knowledge.json",
        event_log=events,
        version_store=versions,
    )

    document = manager.import_file(source_path)
    results = manager.search("كيف أقيس تكلفة الاستفسارات؟")
    restored = BoodaLocalKnowledgeBase(tmp_path / "knowledge.json")

    assert document["format"] == "md"
    assert document["chunks"][0]["page"] is None
    assert results[0]["source"] == str(source_path.resolve())
    assert "الاستفسارات المؤهلة" in results[0]["text"]
    assert restored.search("الاستفسارات المؤهلة")
    assert events.get_events(entity_type="local_document")
    assert versions.history("local_document", document["document_id"])


def test_pdf_import_preserves_page_numbers_and_deduplicates(
    tmp_path, monkeypatch
):
    path = tmp_path / "campaign.pdf"
    path.write_bytes(b"test-pdf")

    class FakePage:
        def extract_text(self):
            return "تكلفة الإعلان ونتائج الحملة"

    class FakeReader:
        pages = [FakePage(), FakePage()]

    monkeypatch.setattr(
        "core.knowledge_base.PdfReader",
        lambda _content, strict: FakeReader(),
    )
    manager = BoodaLocalKnowledgeBase(tmp_path / "knowledge.json")

    first = manager.import_file(path)
    duplicate = manager.import_file(path)
    results = manager.search("نتائج الإعلان", limit=5)

    assert first["document_id"] == duplicate["document_id"]
    assert first["page_count"] == 2
    assert {result["page"] for result in results} == {1, 2}


def test_import_rejects_unsupported_empty_oversized_and_non_utf8_documents(
    tmp_path,
):
    manager = BoodaLocalKnowledgeBase(tmp_path / "knowledge.json")
    unsupported = tmp_path / "data.csv"
    unsupported.write_text("a,b", encoding="utf-8")
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    invalid = tmp_path / "invalid.txt"
    invalid.write_bytes(b"\xff")

    with pytest.raises(ValueError, match="Unsupported document type"):
        manager.import_file(unsupported)
    with pytest.raises(ValueError, match="empty"):
        manager.import_file(empty)
    with pytest.raises(ValueError, match="UTF-8"):
        manager.import_file(invalid)

    large = tmp_path / "large.txt"
    with large.open("wb") as file:
        file.truncate(20 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="20 MiB"):
        manager.import_file(large)


def test_import_and_search_do_not_attempt_network_access(tmp_path, monkeypatch):
    path = tmp_path / "offline.txt"
    path.write_text("مصدر محلي لا يحتاج إلى إنترنت.", encoding="utf-8")

    def reject_network(*_args, **_kwargs):
        raise AssertionError("Local knowledge must not use the network.")

    monkeypatch.setattr("socket.socket.connect", reject_network)
    manager = BoodaLocalKnowledgeBase(tmp_path / "knowledge.json")

    manager.import_file(path)

    assert manager.search("مصدر محلي")


def test_agent_adds_local_source_excerpts_to_planning_context(tmp_path):
    path = tmp_path / "strategy.txt"
    path.write_text(
        "قيسي تكلفة الإعلان بعدد الاستفسارات المؤهلة.",
        encoding="utf-8",
    )
    knowledge_base = BoodaLocalKnowledgeBase(tmp_path / "knowledge.json")
    knowledge_base.import_file(path)

    class ContextPlanner:
        memory = None

        def create_plan(self, goal, memory):
            self.memory = memory
            return BoodaPlan(
                goal.goal_id,
                (PlanStep("draft-plan", "Draft a local plan"),),
            )

    planner = ContextPlanner()
    agent = BoodaAgent(
        planner,
        BoodaTaskManager(),
        BoodaToolRegistry(),
        BoodaExecutor(),
        knowledge_base=knowledge_base,
    )
    agent.intake(BoodaGoal("g", "خطط لقياس تكلفة الإعلان"))
    agent.plan()

    source = planner.memory["local_sources"][0]
    assert source["source"] == str(path.resolve())
    assert source["page"] is None
    assert "الاستفسارات المؤهلة" in source["text"]


def test_local_sources_are_included_in_planner_request(tmp_path):
    source = {
        "title": "strategy",
        "source": "strategy.pdf",
        "page": 3,
        "text": "اختبر نسخة واحدة وغيّر عنصرًا واحدًا في كل مرة.",
    }
    captured = []

    def transport(_endpoint, payload):
        captured.append(payload)
        return {"choices": [{"message": {"content": (
            '{"steps":[{"task_id":"draft","title":"Write",'
            '"description":"Write a supported draft.",'
            '"capability":"draft","depends_on":[],'
            '"permission_name":"draft_content","metadata":{}}]}'
        )}}]}

    planner = OpenAICompatiblePlanner(
        base_url="https://example.test/v1",
        model="test",
        transport=transport,
        capability_permissions={"draft": ("draft_content",)},
    )
    registry = BoodaToolRegistry()
    registry.register("draft", lambda task: task.description)
    permissions = BoodaPermissionManager()
    permissions.add_permission("draft_content", allowed=True)
    planner.configure_agent(registry=registry, permission_manager=permissions)

    planner.create_plan(
        BoodaGoal("source-plan", "اكتب مسودة إعلان"),
        {"local_sources": [source]},
    )

    sent_memory = json.loads(captured[0]["messages"][1]["content"])["memory"]
    assert sent_memory["local_sources"][0]["page"] == 3
    assert sent_memory["local_sources"][0]["source"] == "strategy.pdf"


def test_agent_conversation_searches_local_sources_by_current_question(tmp_path):
    path = tmp_path / "campaign.txt"
    path.write_text("الإعلان الناجح يقيس تكلفة العملاء المحتملين.", encoding="utf-8")
    knowledge_base = BoodaLocalKnowledgeBase(tmp_path / "knowledge.json")
    knowledge_base.import_file(path)

    class ConversationalPlanner:
        received_memory = None

        def create_plan(self, goal, _memory):
            return BoodaPlan(goal.goal_id, (PlanStep("noop", "No-op"),))

        def respond(self, _message, *, context, memory):
            self.received_memory = memory
            return "الإجابة مستندة إلى المصدر المحلي."

    planner = ConversationalPlanner()
    agent = BoodaAgent(
        planner,
        BoodaTaskManager(),
        BoodaToolRegistry(),
        BoodaExecutor(),
        knowledge_base=knowledge_base,
    )
    agent.intake(BoodaGoal("g", "مساعدة عامة"))

    answer = agent.respond("كيف أقيس تكلفة العملاء المحتملين؟")

    assert answer
    assert planner.received_memory["local_sources"][0]["source"] == str(
        path.resolve()
    )


def test_local_knowledge_cli_import_search_and_delete(
    tmp_path, monkeypatch, capsys
):
    path = tmp_path / "notes.txt"
    path.write_text("تحليل نتائج الحملة.", encoding="utf-8")
    manager = BoodaLocalKnowledgeBase(tmp_path / "knowledge.json")
    answers = iter([
        "1", str(path), "2", "نتائج الحملة", "4",
        manager.import_file(path)["document_id"], "0",
    ])
    monkeypatch.setattr(builtins, "input", lambda _prompt: next(answers))

    manage_local_knowledge_base(manager)

    output = capsys.readouterr().out
    assert "تم استيراد notes" in output
    assert "تحليل نتائج الحملة" in output
    assert "تم حذف المصدر ومقاطعه." in output
    assert manager.list_documents() == []
