from copy import deepcopy
import json
from pathlib import Path
import pytest
from core.knowledge_base import BoodaLocalKnowledgeBase
from tools.teach_examples import teach_examples

PACK = Path(__file__).resolve().parents[1] / "knowledge/curriculum/booda_teacher_examples.json"


def test_teacher_pack_is_private_retrievable_idempotent_and_does_not_train_weights(tmp_path):
    report = teach_examples(PACK, root=tmp_path)
    assert len(report["documents"]) == 12 and not report["model_weights_changed"]
    assert report["confirmed_personal_facts_added"] == 0 and not report["external_services_called"]
    kb = BoodaLocalKnowledgeBase(tmp_path / "knowledge/local_documents.json")
    sources = kb.search("إثبات نجاح الحملة مقاييس الإنفاق النتائج مصدر القياس")
    assert any("العبارة وحدها" in source["text"] for source in sources)
    assert all(source["private"] for source in sources)
    repeated = teach_examples(PACK, root=tmp_path)
    assert repeated["documents"] == report["documents"]


def test_import_rejects_whole_invalid_pack_before_any_kb_write(tmp_path):
    data = json.loads(PACK.read_text(encoding="utf-8"))
    data["examples"][-1].pop("check")
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError): teach_examples(path, root=tmp_path)
    assert not (tmp_path / "knowledge/local_documents.json").exists()


def test_external_teacher_is_attributed_and_client_scoped_not_promoted_to_fact(tmp_path):
    data = json.loads(PACK.read_text(encoding="utf-8"))
    data["teacher"] = "Gemini"
    data["scope"] = {"client_id": "a"}
    data["examples"] = [deepcopy(data["examples"][0])]
    path = tmp_path / "teacher.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    report = teach_examples(path, root=tmp_path)
    kb = BoodaLocalKnowledgeBase(tmp_path / "knowledge/local_documents.json")
    assert not kb.search("الدقة والحساب", client_id="b")
    sources = kb.search("الدقة والحساب", client_id="a")
    assert "المعلم المعلن: Gemini" in sources[0]["text"]
    assert report["confirmed_personal_facts_added"] == 0
