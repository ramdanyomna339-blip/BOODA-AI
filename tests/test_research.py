import pytest

from core.knowledge_base import BoodaLocalKnowledgeBase
from core.research import BoodaResearchManager, WikipediaSearch
from core.research_cli import manage_research


class Provider:
    def __init__(self):
        self.calls = []

    def search(self, query, **kwargs):
        self.calls.append((query, kwargs))
        return [{"title": "التسويق", "text": "التسويق يعتمد على دراسة الجمهور.",
                 "source": "https://ar.wikipedia.org/wiki/Marketing", "publisher": "Wikipedia"}]


def manager(tmp_path, **kwargs):
    return BoodaResearchManager(tmp_path / "research.json", output_dir=tmp_path / "reports", **kwargs)


def test_offline_search_and_report_preserve_source_page_without_network(tmp_path):
    document = tmp_path / "source.md"
    document.write_text("التسويق ودراسة الجمهور", encoding="utf-8")
    kb = BoodaLocalKnowledgeBase(tmp_path / "kb.json")
    kb.import_file(document)
    provider = Provider()
    research = manager(tmp_path, knowledge_base=kb, provider=provider)
    session = research.research("التسويق")
    assert not provider.calls
    assert session["sources"][0]["source"] == str(document.resolve())
    assert "page" in session["sources"][0]
    report = research.export_report(session["id"]).read_text(encoding="utf-8")
    assert "S1" in report and "التسويق" in report


def test_pending_rejected_and_approved_recall_persist(tmp_path):
    research = manager(tmp_path, provider=Provider())
    session = research.research("التسويق", online=True)
    finding = research.propose(session["id"], "التسويق يحتاج دراسة", ["S1"], usefulness="تحسين خطة العميل")
    assert research.approved_knowledge("التسويق") == []
    with pytest.raises(ValueError):
        research.propose(session["id"], "ادعاء", ["S2"], usefulness="اختبار")
    with pytest.raises(ValueError):
        research.record_application(session["id"], finding["id"], task_id="t1", observation="نتيجة")
    research.review(session["id"], finding["id"], approve=True)
    restored = manager(tmp_path)
    assert restored.approved_knowledge("التسويق")[0]["verification"] == "not_independently_verified"
    restored.record_application(session["id"], finding["id"], task_id="t1", observation="زيادة موثقة")
    assert restored.get(session["id"])["applications"][0]["improved"] is None
    restored.review(session["id"], finding["id"], approve=False)
    assert restored.approved_knowledge("التسويق") == []


def test_failed_online_search_has_no_fake_sources(tmp_path):
    class Broken:
        def search(self, *args, **kwargs):
            raise OSError("offline")
    research = manager(tmp_path, provider=Broken())
    session = research.research("موضوع", online=True)
    assert session["status"] == "partial"
    assert session["errors"] and not session["sources"]


def test_online_sends_only_explicit_topic_and_invalid_input_is_rejected(tmp_path):
    provider = Provider()
    research = manager(tmp_path, provider=provider)
    research.research("التسويق", online=True)
    assert provider.calls == [("التسويق", {"language": "ar", "limit": 5})]
    with pytest.raises(ValueError):
        research.research(" ")
    with pytest.raises(ValueError):
        WikipediaSearch().search("test", language="localhost")


def test_cli_cancel_review_leaves_pending(tmp_path, monkeypatch):
    research = manager(tmp_path, provider=Provider())
    session = research.research("التسويق", online=True)
    finding = research.propose(session["id"], "معلومة", ["S1"], usefulness="خطة")
    answers = iter(["4", session["id"], finding["id"], "إلغاء", "0"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    manage_research(research)
    assert research.get(session["id"])["findings"][0]["status"] == "pending"


def test_wikipedia_request_and_source_metadata(monkeypatch):
    import json
    seen = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            assert limit == 1_000_001
            return json.dumps({"query": {"pages": [{"title": "Marketing", "index": 1,
                                "extract": "An introduction.", "revisions": [{"timestamp": "2026-01-01T00:00:00Z"}]}]}}).encode()

    class Opener:
        def open(self, request, timeout):
            seen.append((request.full_url, timeout))
            return Response()

    monkeypatch.setattr("core.research.build_opener", lambda *args: Opener())
    source = WikipediaSearch().search("Marketing", language="en", limit=1)[0]
    assert source["updated_at"] == "2026-01-01T00:00:00Z"
    assert source["source"] == "https://en.wikipedia.org/wiki/Marketing"
    assert seen[0][0].startswith("https://en.wikipedia.org/w/api.php?")
    assert seen[0][1] == 15
