"""Real offline model, scanned PDF and browser acceptance on disposable fixtures."""
import io
import json
from pathlib import Path
import site
import tempfile
import threading
import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-semantic", action="store_true")
    options = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    site.addsitedir(str(root / ".desktop-deps"))
    from PIL import Image, ImageDraw
    from core.knowledge_base import BoodaLocalKnowledgeBase
    from core.arabic_console import ArabicConsole, create_server
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory(prefix="booda-acceptance-") as directory:
        temporary = Path(directory)
        if options.skip_semantic:
            import os
            os.environ["BOODA_EMBEDDING_MODEL"] = str(temporary / "disabled")
        kb = BoodaLocalKnowledgeBase(temporary / "kb.json")
        source = temporary / "vehicles.txt"
        source.write_text("شراء سيارة جديدة من الوكيل", encoding="utf-8")
        kb.import_file(source)
        if not options.skip_semantic:
            results = kb.search("اقتناء مركبة حديثة")
            assert results and kb.search_mode == "hybrid", "Real semantic retrieval unavailable"
        image = Image.new("RGB", (1200, 600), "white")
        draw = ImageDraw.Draw(image)
        draw.text((80, 150), "Budget 1200", fill="black", font_size=72)
        raw = io.BytesIO()
        image.save(raw, "PDF", resolution=120)
        image.close()
        scan = temporary / "scan.pdf"
        scan.write_bytes(raw.getvalue())
        document = kb.import_file(scan, ocr=True)
        assert any("1200" in chunk["text"] and chunk["method"] == "ocr" for chunk in document["chunks"])
        ui = root / "tools/arabic_ui"
        page = {name:(ui / ("app." + suffix)).read_text(encoding="utf-8")
                for name, suffix in (("html","html"),("js","js"),("css","css"))}
        console = ArabicConsole()
        console.write("أهلًا بك في بودا. اختر المستند أو ابحث في المكتبة.")
        server, token = create_server(console, page, knowledge_base=kb)
        listener = threading.Thread(target=server.serve_forever, daemon=True)
        listener.start()
        output = root / "outputs/document_upgrade_acceptance"
        output.mkdir(parents=True, exist_ok=True)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                tab = browser.new_page(viewport={"width":1280,"height":1000})
                errors = []
                tab.on("pageerror", lambda error: errors.append(str(error)))
                tab.goto(f"http://127.0.0.1:{server.server_port}/#token={token}")
                tab.locator("#attachment").set_input_files({"name":"notes.txt","mimeType":"text/plain","buffer":"فواتير الحملة بقيمة 1700 جنيه".encode()})
                tab.locator("#upload").click()
                tab.get_by_text("تمت إضافة notes", exact=False).wait_for()
                tab.locator("#query").fill("فواتير")
                tab.locator("#search-form button").click()
                tab.locator("#sources article").first.wait_for()
                assert "1700" in tab.locator("#sources").inner_text()
                tab.screenshot(path=str(output / "interface.png"), full_page=True)
                tab.set_viewport_size({"width":390,"height":844})
                tab.screenshot(path=str(output / "mobile.png"), full_page=True)
                assert tab.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
        (output / "report.json").write_text(json.dumps({"semantic_arabic":not options.skip_semantic,"scanned_pdf_ocr":True,"browser_upload_search":True,"mobile_width":True}, indent=2), encoding="utf-8")
        print(output)


if __name__ == "__main__":
    main()
