"""Launch the existing Booda console through a locally rendered Arabic UI."""
import argparse
from pathlib import Path
import site
import sys
import threading
import time
import webbrowser
import os
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--demo", action="store_true")
    options = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    search_python = root / ".search-venv/Scripts/python.exe"
    if search_python.is_file() and Path(sys.prefix).resolve() != (root / ".search-venv").resolve() and not os.environ.get("BOODA_SEARCH_RELAUNCHED"):
        environment = dict(os.environ, BOODA_SEARCH_RELAUNCHED="1")
        return subprocess.call([str(search_python), "-m", "tools.arabic_desktop", *sys.argv[1:]], cwd=root, env=environment)
    deps = root / ".desktop-deps"
    if deps.is_dir():
        if Path(sys.prefix).resolve() != (root / ".search-venv").resolve():
            sys.path.insert(0, str(deps))
        site.addsitedir(str(deps))
    from core.arabic_console import ArabicConsole, create_server
    ui = root / "tools/arabic_ui"
    page = {name: (ui / ("app." + suffix)).read_text(encoding="utf-8")
            for name, suffix in (("html", "html"), ("js", "js"), ("css", "css"))}
    console = ArabicConsole()
    from core.knowledge_base import BoodaLocalKnowledgeBase
    attachment_library = BoodaLocalKnowledgeBase(root / "knowledge/local_documents.json")
    server, token = create_server(console, page, knowledge_base=attachment_library)
    url = f"http://127.0.0.1:{server.server_port}/#token={token}"
    print("Booda Arabic interface: " + url, flush=True)
    def application():
        if options.demo:
            print("اختبار بودا: كل خطوة بموافقتي.\nالعربية متصلة واتجاهها من اليمين إلى اليسار.\nملف report-123.txt — العدد 123 — الرابط https://example.com")
            result = input("اكتبي نصًا عربيًا للتجربة، أو 0 للخروج: ")
            if result != "0":
                print("النص الأصلي: " + result)
                input("انتهى العرض التجريبي. اضغطي إرسال للخروج: ")
        else:
            # Import after installing the input/getpass bridge.
            from core.main import main as run_booda
            run_booda(shared_knowledge_base=attachment_library)
    listener = threading.Thread(target=server.serve_forever, daemon=True)
    worker = threading.Thread(target=console.run, args=(application,), daemon=True)
    listener.start()
    if not options.no_browser:
        webbrowser.open(url, new=2)
    worker.start()
    try:
        while worker.is_alive():
            worker.join(timeout=.5)
        time.sleep(5)
    except KeyboardInterrupt:
        console.finish()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
