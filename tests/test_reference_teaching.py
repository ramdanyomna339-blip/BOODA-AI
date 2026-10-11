from core.knowledge_base import BoodaLocalKnowledgeBase
from core.llm_planner import OpenAICompatiblePlanner
from tools.teach_reference import teach_reference


def test_private_reference_keeps_status_on_each_excerpt_and_never_leaves_for_remote(tmp_path):
    path = tmp_path / "reference.md"
    path.write_text("ميزانية قديمة غير مؤكدة " * 150, encoding="utf-8")
    kb = BoodaLocalKnowledgeBase(tmp_path / "documents.json")
    record = kb.import_file(path, private=True, reference_status="unverified_historical")
    results = kb.search("ميزانية", limit=20)
    assert len(results) > 1
    assert all(item["private"] and item["reference_status"] == "unverified_historical"
               and "not current confirmed" in item["usage_note"] for item in results)
    remote = OpenAICompatiblePlanner(base_url="https://example.com/v1", model="test")
    assert remote._memory_for_planner({"local_sources": results})["local_sources"] == []
    local = OpenAICompatiblePlanner(base_url="http://127.0.0.1:8080/v1", model="test")
    assert local._memory_for_planner({"local_sources": results})["local_sources"] == results
    assert kb.import_file(path)["private"] is True


def test_teaching_is_idempotent_and_preserves_candidates_without_approving_them(tmp_path):
    source = tmp_path / "reference.md"
    source.write_text(
        "## تاسعًا: أمثلة\n### 1. تعديل العبوة\nحافظ على العبوة في هذا الطلب فقط.\n"
        "## عاشرًا: قواعد\n"
        "| B001 | اسم محتمل | المستخدمة | هوية | M1 | منقول | متغير | مجهول | نعم |\n",
        encoding="utf-8",
    )
    first = teach_reference(source, root=tmp_path / "project")
    second = teach_reference(source, root=tmp_path / "project")
    assert first["documents"] == second["documents"]
    assert first["candidate_records"] == 1
    assert len(first["lessons"]) == 1
    assert first["confirmed_personal_facts_added"] == 0
    assert first["model_weights_changed"] is False
    kb = BoodaLocalKnowledgeBase(tmp_path / "project/knowledge/local_documents.json")
    assert len(kb.list_documents()) == 2
    assert all(item["private"] for item in kb.search("العبوة"))
