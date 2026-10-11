import base64
import json
import threading
import urllib.request
import urllib.error
import zipfile

import pytest

from core.knowledge_base import BoodaLocalKnowledgeBase
from core.arabic_console import ArabicConsole, create_server


def test_word_import_is_searchable_and_rejects_silent_truncation(tmp_path, monkeypatch):
    path = tmp_path / "مستند.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>ميزانية الحملة ألف جنيه</w:t></w:r></w:p></w:body></w:document>')
    kb = BoodaLocalKnowledgeBase(tmp_path / "kb.json")
    kb.import_file(path)
    assert "ألف" in kb.search("ميزانية")[0]["text"]
    import hashlib
    monkeypatch.setattr("core.document_reader.read_document", lambda *args: {
        "text":"partial", "truncated":True, "sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
    with pytest.raises(ValueError, match="split"):
        kb.import_file(path)


def test_spreadsheet_import(tmp_path):
    from openpyxl import Workbook
    path = tmp_path / "budget.xlsx"
    book = Workbook()
    book.active.append(["ميزانية", 1200])
    book.save(path)
    kb = BoodaLocalKnowledgeBase(tmp_path / "kb.json")
    kb.import_file(path)
    assert "1200" in kb.search("ميزانية")[0]["text"]


def test_ocr_only_empty_pdf_pages_and_keep_page_sources(tmp_path, monkeypatch):
    class Page:
        def __init__(self, text): self.text = text
        def extract_text(self): return self.text
    class Reader:
        pages = [Page("ميزانية الحملة"), Page("")]
    monkeypatch.setattr("core.knowledge_base.PdfReader", lambda *a, **kw: Reader())
    calls = []
    def ocr(raw, index):
        calls.append(index)
        return "فواتير الحملة"
    monkeypatch.setattr("core.pdf_ocr.read_pdf_page", ocr)
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"fixture")
    kb = BoodaLocalKnowledgeBase(tmp_path / "kb.json")
    kb.import_file(path, ocr=True)
    result = kb.search("فواتير")[0]
    assert calls == [1]
    assert result["page"] == 2 and result["extraction_method"] == "ocr"


def test_semantic_search_cannot_cross_project_scope_and_falls_back(tmp_path):
    class Semantic:
        def scores(self, query, texts): return [.9] * len(texts)
    kb = BoodaLocalKnowledgeBase(tmp_path / "kb.json", semantic_search=Semantic())
    path = tmp_path / "a.txt"
    path.write_text("معلومة تخص العميل", encoding="utf-8")
    kb.import_file(path, project_id="A")
    assert kb.search("مترادف", project_id="B") == []
    assert kb.search("مترادف", project_id="A")[0]["search_mode"] == "hybrid"
    kb.semantic_search.scores = lambda *args: (_ for _ in ()).throw(RuntimeError())
    assert kb.search("معلومة", project_id="A")[0]["search_mode"] == "lexical_fallback"


def test_upload_auth_search_and_filename_guards(tmp_path):
    kb = BoodaLocalKnowledgeBase(tmp_path / "kb.json")
    console = ArabicConsole()
    server, token = create_server(console, {"html":"", "js":"", "css":""}, knowledge_base=kb)
    listener = threading.Thread(target=server.serve_forever, daemon=True)
    listener.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def post(route, data, authenticated=True):
        headers = {"Origin": origin, "Content-Type":"application/json"}
        if authenticated: headers["X-Booda-Token"] = token
        request = urllib.request.Request(origin + route, data=json.dumps(data).encode(), headers=headers)
        with opener.open(request) as response: return json.load(response)
    data = {"name":"notes.txt", "content":base64.b64encode("ميزانية المشروع".encode()).decode()}
    try:
        with pytest.raises(urllib.error.HTTPError): post("/documents", data, False)
        with pytest.raises(urllib.error.HTTPError): post("/documents", dict(data, name="../escape.txt"))
        with pytest.raises(urllib.error.HTTPError): post("/documents", dict(data, content="not base64"))
        assert post("/documents", data)["chunks"] == 1
        result = post("/search", {"query":"ميزانية"})["results"][0]
        assert result["source"] == "attachment:notes.txt" and result["private"]
        assert BoodaLocalKnowledgeBase(tmp_path / "kb.json").search("ميزانية")
    finally:
        server.shutdown()
        server.server_close()


def test_secret_answers_do_not_enter_conversation_history():
    console = ArabicConsole()
    worker = threading.Thread(target=lambda: console.ask("secret", secret=True))
    worker.start()
    with console.condition:
        console.condition.wait_for(lambda: console.pending is not None, timeout=2)
        prompt = console.pending["id"]
    console.submit(prompt, "private-password")
    worker.join(2)
    assert "private-password" not in json.dumps(console.state())


def test_hybrid_search_rejects_weak_semantics_with_one_generic_word(tmp_path):
    class WeakSemantic:
        def scores(self, query, texts): return [.3] * len(texts)
    kb = BoodaLocalKnowledgeBase(tmp_path / "kb.json", semantic_search=WeakSemantic())
    path = tmp_path / "history.txt"
    path.write_text("حديثة معلومات تاريخية", encoding="utf-8")
    kb.import_file(path)
    assert kb.search("اقتناء مركبة حديثة") == []
