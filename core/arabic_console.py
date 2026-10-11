"""Local browser console: logical Unicode text, native Arabic shaping and bidi."""
import builtins
from contextlib import redirect_stdout, redirect_stderr
import getpass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading
import base64
from pathlib import Path
import tempfile


class ArabicConsole:
    encoding = "utf-8"
    def __init__(self):
        self.condition = threading.Condition()
        self.text = ""
        self.pending = None
        self.answer = None
        self.finished = False
        self.revision = 0
        self.messages = []
        self.output_start = 0

    def write(self, text):
        with self.condition:
            self.text = (self.text + str(text))[-200000:]
            self.revision += 1
        return len(text)

    def flush(self): pass
    def isatty(self): return False

    def ask(self, prompt="", *, secret=False):
        with self.condition:
            self.pending = {"id": secrets.token_urlsafe(18), "prompt": str(prompt), "secret": secret}
            self.answer = None
            self.revision += 1
            self.condition.wait_for(lambda: self.answer is not None or self.finished)
            if self.finished:
                raise EOFError("Interface stopped")
            answer = self.answer
            self.pending = self.answer = None
            self.revision += 1
            return answer

    def submit(self, prompt_id, value):
        with self.condition:
            if not self.pending or self.pending["id"] != prompt_id or self.answer is not None or self.finished:
                return False
            self.answer = value
            if not self.pending["secret"]:
                self.messages.extend([
                    {"role": "assistant", "text": self.text[self.output_start:] + self.pending["prompt"]},
                    {"role": "user", "text": value},
                ])
                self.messages = self.messages[-100:]
            self.output_start = len(self.text)
            self.condition.notify_all()
            return True

    def state(self):
        with self.condition:
            return {"text": self.text, "pending": dict(self.pending) if self.pending and self.answer is None else None,
                    "finished": self.finished, "revision": self.revision,
                    "messages": list(self.messages)}

    def finish(self):
        with self.condition:
            self.finished = True
            self.pending = None
            self.revision += 1
            self.condition.notify_all()

    def run(self, application):
        original_input, original_getpass = builtins.input, getpass.getpass
        builtins.input = self.ask
        getpass.getpass = lambda prompt="Password: ", stream=None: self.ask(prompt, secret=True)
        try:
            with redirect_stdout(self), redirect_stderr(self):
                application()
        except EOFError:
            pass
        except Exception:
            self.write("\nتعذر إكمال الجلسة. أعد التشغيل، أو استخدم وضع نافذة الأوامر لعرض التشخيص.\n")
        finally:
            builtins.input, getpass.getpass = original_input, original_getpass
            self.finish()


def create_server(console, page, *, knowledge_base=None):
    token = secrets.token_urlsafe(32)
    document_lock = threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def send_body(self, status, content, media="application/json; charset=utf-8"):
            raw = content.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", media)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(raw)
        def valid_host(self):
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"
        def authorized(self):
            return secrets.compare_digest(self.headers.get("X-Booda-Token", ""), token)
        def do_GET(self):
            if not self.valid_host():
                return self.send_body(403, "{}")
            if self.path == "/":
                return self.send_body(200, page["html"], "text/html; charset=utf-8")
            if self.path in {"/app.js", "/app.css"}:
                key = "js" if self.path.endswith(".js") else "css"
                return self.send_body(200, page[key], "text/javascript; charset=utf-8" if key == "js" else "text/css; charset=utf-8")
            if self.path == "/state" and self.authorized():
                return self.send_body(200, json.dumps(console.state(), ensure_ascii=False))
            return self.send_body(403, "{}")
        def do_POST(self):
            origin = f"http://127.0.0.1:{self.server.server_port}"
            if not self.valid_host() or not self.authorized() or self.headers.get("Origin") != origin or self.path not in {"/answer", "/documents", "/search"}:
                return self.send_body(403, "{}")
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= (28_000_000 if self.path == "/documents" else 100000):
                    raise ValueError()
                data = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError()
                if self.path in {"/documents", "/search"}:
                    if knowledge_base is None:
                        return self.send_body(404, "{}")
                    with document_lock, knowledge_base.lock:
                        if self.path == "/search":
                            results = knowledge_base.search(data.get("query"), limit=5)
                            return self.send_body(200, json.dumps({"results": results, "mode": knowledge_base.search_mode}, ensure_ascii=False))
                        name = data.get("name")
                        if not isinstance(name, str) or Path(name).name != name or len(name) > 180 or ":" in name or "\\" in name:
                            raise ValueError()
                        raw = base64.b64decode(data.get("content", ""), validate=True)
                        if not 0 < len(raw) <= 20_000_000 or not isinstance(data.get("ocr", False), bool):
                            raise ValueError()
                        with tempfile.TemporaryDirectory(prefix="booda-upload-") as directory:
                            path = Path(directory) / name
                            path.write_bytes(raw)
                            document = knowledge_base.import_file(path, private=True, ocr=data.get("ocr", False))
                            # Persist the user-facing filename rather than a deleted temporary path.
                            stored = knowledge_base.data["documents"][document["document_id"]]
                            stored["source"] = "attachment:" + name
                            knowledge_base._save()
                        return self.send_body(200, json.dumps({"title": stored["title"], "chunks": len(stored["chunks"])}, ensure_ascii=False))
                if not isinstance(data.get("value"), str) or not isinstance(data.get("id"), str):
                    raise ValueError()
            except (ValueError, UnicodeError, AttributeError, TypeError, ImportError, OSError):
                return self.send_body(400, json.dumps({"error": "تعذرت القراءة. راجع نوع الملف وحجمه وتجهيز OCR؛ قد يتجاوز حدود الاستخراج."}, ensure_ascii=False))
            accepted = console.submit(data["id"], data["value"])
            return self.send_body(200 if accepted else 409, json.dumps({"accepted": accepted}))
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    return server, token
