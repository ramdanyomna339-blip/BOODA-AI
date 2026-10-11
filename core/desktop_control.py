"""Single-action, human-approved desktop requests; no autonomous approval path."""

import copy
import hashlib
import json
import time
import uuid
from pathlib import Path
from urllib.parse import quote_plus

from core.executor import BoodaExecutor
from core.permission_policy import BoodaPermissionPolicy
from core.research_web import public_url
from core.task import BoodaTask

DESKTOP_PERMISSION = "desktop_control"
FILE_OPERATIONS = {"read_document", "download_media", "inspect_media"}
VIDEO_OPERATIONS = {"discover_video", "youtube_captions"}
REVIEW_OPERATIONS = {"excerpt_summary", "save_correction", "recall_corrections"}
OPERATIONS = {"observe", "watch", "assist", "move", "click", "drag", "scroll", "type", "key", "open_url", "search", "transcribe", "launch_app", "play_media", "restore_window", "read_elements", "verify_text", "read_webpage", "read_captions", "ocr_screen", "browser_open", "browser_read", "browser_click", "browser_fill"}
OPERATIONS |= FILE_OPERATIONS
OPERATIONS |= VIDEO_OPERATIONS
OPERATIONS |= REVIEW_OPERATIONS


class BoodaDesktopController:
    def __init__(self, backend, *, clock=time.monotonic):
        self.backend = backend
        self.clock = clock
        self.session = uuid.uuid4().hex
        self.pending = {}
        self.stopped = False

    def stop(self):
        """Invalidate every outstanding request. A new controller starts a new session."""
        self.stopped = True
        self.pending.clear()
        close = getattr(self.backend, "close", None)
        if close:
            close()

    def prepare(self, operation, parameters=None):
        if self.stopped:
            raise ValueError("Connection stopped; reconnect explicitly.")
        if operation not in OPERATIONS | FILE_OPERATIONS:
            raise ValueError("Unsupported desktop operation.")
        parameters = copy.deepcopy(parameters or {})
        self.backend.validate(operation, parameters)
        # This is only foreground metadata, never screenshot/text extraction.
        target = getattr(self.backend, "review_target", self.backend.target)() if operation in {"move", "click", "drag", "scroll", "type", "key", "read_elements", "verify_text"} else None
        payload = {"session": self.session, "operation": operation, "parameters": parameters,
                   "target": target, "nonce": uuid.uuid4().hex}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
        task = BoodaTask("desktop-" + digest, f"Desktop: {operation}", metadata=payload)
        self.pending[task.task_id] = (copy.deepcopy(payload), self.clock())
        return task

    def execute(self, task, *, permission_manager, approval=None, audit_log=None):
        saved = self.pending.pop(task.task_id, None)
        if self.stopped or saved is None:
            raise ValueError("Stopped, unknown, or previously attempted request.")
        payload, created = saved
        if task.metadata != payload or self.clock() - created > 120:
            raise ValueError("Request changed or expired; review a new request.")
        permission = permission_manager.get_permission(DESKTOP_PERMISSION)
        if permission is None or permission.risk_level not in {"high", "critical"}:
            raise ValueError("Desktop access requires high-risk permission and one-time approval.")

        def action():
            if self.stopped:
                raise ValueError("Connection stopped.")
            if payload["target"] is not None and self.backend.target() != payload["target"]:
                raise ValueError("Foreground window changed; review again.")
            self.backend.validate(payload["operation"], payload["parameters"])
            return self.backend.perform(payload["operation"], payload["parameters"])

        return BoodaExecutor().execute(task, action, permission_manager=permission_manager,
            permission_name=DESKTOP_PERMISSION, permission_policy=BoodaPermissionPolicy(),
            approval=approval, audit_log=audit_log, requested_by="desktop_connection")


class WindowsDesktopBackend:
    """Independent public Windows APIs; never relies on Codex's UI helper."""
    def __init__(self, output_root="outputs/desktop", media_root=None, model_path=None):
        import ctypes
        import os
        if os.name != "nt":
            raise RuntimeError("The native desktop backend requires Windows.")
        import pyautogui
        self.ui = pyautogui
        self.ui.FAILSAFE = True
        self.ui.PAUSE = 0.15
        self.user32 = ctypes.windll.user32
        self.user32.GetForegroundWindow.restype = ctypes.c_void_p
        self.output = Path(output_root).resolve()
        self.media_root = Path(media_root).resolve(strict=True) if media_root else None
        self.model_path = Path(model_path).resolve(strict=True) if model_path else None
        self.selected_window = None
        self.browser_tools = None

    def close(self):
        if self.browser_tools is not None:
            self.browser_tools.close()
            self.browser_tools = None

    def _window(self, hwnd):
        import ctypes
        if not hwnd:
            raise ValueError("No foreground window; unlock the desktop first.")
        title = ctypes.create_unicode_buffer(1024)
        self.user32.GetWindowTextW(ctypes.c_void_p(hwnd), title, len(title))
        pid = ctypes.c_ulong()
        self.user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
        if not pid.value:
            raise ValueError("Window no longer has a valid process; select it again.")
        from ctypes import wintypes
        rect = wintypes.RECT()
        if not self.user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect)):
            raise ValueError("Window bounds are unavailable; select it again.")
        return {"window": int(hwnd), "pid": pid.value, "title": title.value,
                "bounds": [rect.left, rect.top, rect.right, rect.bottom]}

    def target(self):
        return self._window(self.user32.GetForegroundWindow())

    def windows(self):
        import ctypes
        rows = []
        callback = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def collect(hwnd, unused):
            if self.user32.IsWindowVisible(ctypes.c_void_p(hwnd)):
                item = self._window(hwnd)
                if item["title"]:
                    rows.append(item)
            return True
        self.user32.EnumWindows(callback(collect), 0)
        return rows

    def review_target(self):
        if self.selected_window is None:
            raise ValueError("Choose a target window before preparing an input action.")
        current = self._window(self.selected_window["window"])
        left, top, right, bottom = current["bounds"]
        width, height = self.ui.size()
        if (right <= 0 or bottom <= 0 or left >= width or top >= height
                or right <= left or bottom <= top):
            raise ValueError("النافذة مصغّرة أو خارج الشاشة. أظهرها أولًا، ثم اخترها من جديد.")
        if current != self.selected_window:
            raise ValueError("Selected window changed; select it again.")
        return current

    def _point(self, parameters, suffix=""):
        width, height = self.ui.size()
        x, y = parameters["x" + suffix], parameters["y" + suffix]
        if type(x) is not int or type(y) is not int or not (1 <= x < width - 1 and 1 <= y < height - 1):
            raise ValueError("Point must be inside the main screen, away from failsafe corners.")
        if self.selected_window is not None:
            left, top, right, bottom = self.review_target()["bounds"]
            if not left <= x < right or not top <= y < bottom:
                raise ValueError("Point lies outside the selected window.")

    def validate(self, operation, p):
        fields = {"observe": set(), "move": {"x", "y"}, "click": {"x", "y", "button"},
                  "drag": {"x", "y", "x2", "y2"}, "scroll": {"amount", "x", "y"}, "type": {"text"},
                  "key": {"key"}, "open_url": {"url"}, "search": {"query"}, "transcribe": {"path"},
                  "watch": {"duration", "interval", "endpoint", "model"}, "launch_app": {"application"}, "play_media": {"path"}, "assist": {"question"}}
        expected = fields.get(operation)
        if operation == "excerpt_summary":
            expected = {"text"}
            if not isinstance(p.get("text"), str) or not p["text"].strip() or len(p["text"]) > 30000:
                raise ValueError("التلخيص يحتاج نصًا حتى 30 ألف حرف.")
        if operation in {"save_correction", "recall_corrections"}:
            expected = {"request", "correction"} if operation == "save_correction" else {"request"}
            for field in expected:
                if not isinstance(p.get(field), str) or not p[field].strip() or len(p[field]) > 1000:
                    raise ValueError("الطلب والتصحيح يحتاجان نصًا حتى 1000 حرف.")
        if operation in VIDEO_OPERATIONS:
            expected = {"url", "language"} if operation == "youtube_captions" else {"url"}
            public_url(p.get("url"))
            if operation == "youtube_captions":
                from core.youtube_captions import youtube_video_id
                youtube_video_id(p["url"])
                if p.get("language") not in {"ar", "en"}:
                    raise ValueError("اختر ar أو en للغة الترجمة.")
        if operation in {"read_document", "inspect_media"}:
            expected = {"path"}
            if operation == "read_document":
                from core.document_reader import selected_file
                if self.media_root is None:
                    raise ValueError("حدد مجلد الملفات المسموح به عند بدء الاتصال.")
                selected_file(self.media_root, p.get("path"))
            else:
                self._media(p.get("path"))
        if operation == "download_media":
            from core.laptop import BoodaLaptopConnection
            if self.media_root is None:
                raise ValueError("حدد مجلد التنزيل المسموح عند بدء الاتصال.")
            BoodaLaptopConnection(self.media_root)._path("booda-downloads", directory=True)
            expected = {"url"}
            public_url(p.get("url"))
        if operation in {"read_webpage", "read_captions", "browser_open"}:
            expected = {"url"}
            public_url(p.get("url"))
        if operation in {"ocr_screen", "browser_read"}:
            expected = set()
        if operation in {"browser_click", "browser_fill"}:
            expected = {"snapshot", "role", "name"}
            if operation == "browser_fill":
                expected.add("text")
            if p.get("role") not in ({"textbox"} if operation == "browser_fill" else {"button", "link"}):
                raise ValueError("نوع عنصر المتصفح غير مناسب للعملية.")
            for field in expected - {"role"}:
                limit = 2000 if field == "text" else 200
                if not isinstance(p.get(field), str) or not p[field].strip() or len(p[field]) > limit:
                    raise ValueError("بيانات عنصر المتصفح غير صالحة.")
        if operation == "restore_window":
            expected = {"window", "pid", "title", "bounds"}
        if operation == "read_elements":
            expected = set()
        if operation == "verify_text":
            expected = {"expected"}
        if operation == "assist" and "propose" in p:
            expected = expected | {"propose"}
            if type(p["propose"]) is not bool:
                raise ValueError("Proposal mode must be explicitly true or false.")
        if expected is None or set(p) != expected:
            raise ValueError("Unexpected or missing action parameters.")
        if operation == "restore_window":
            if type(p["window"]) is not int or p != self._window(p["window"]):
                raise ValueError("تغيرت النافذة؛ اخترها من جديد قبل الموافقة.")
        if operation == "verify_text" and (not isinstance(p["expected"], str)
                or not p["expected"].strip() or len(p["expected"]) > 500):
            raise ValueError("اكتب النص المتوقع، بحد أقصى 500 حرف.")
        if operation in {"move", "click", "drag", "scroll"}:
            self._point(p)
        if operation == "drag":
            self._point(p, "2")
        if operation == "click" and p["button"] not in {"left", "right", "middle"}:
            raise ValueError("Unknown mouse button.")
        if operation == "scroll" and (type(p["amount"]) is not int or not -20 <= p["amount"] <= 20):
            raise ValueError("Scroll is limited to 20 steps per approval.")
        if operation == "type" and (not isinstance(p["text"], str) or not p["text"] or len(p["text"]) > 2000 or any(ord(c) < 32 for c in p["text"])):
            raise ValueError("Type plain text up to 2000 characters; approve Enter separately.")
        if operation == "key" and p["key"] not in {"enter", "space", "tab", "esc", "backspace", "left", "right", "up", "down", "home", "end", "ctrl+a", "ctrl+c", "ctrl+v", "ctrl+l", "alt+left"}:
            raise ValueError("Unsupported keyboard shortcut.")
        if operation == "open_url":
            public_url(p["url"])
            import ipaddress
            from urllib.parse import urlsplit
            host = urlsplit(p["url"]).hostname
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                if "." not in host or host.endswith((".local", ".localhost", ".internal")):
                    raise ValueError("Choose a public website.")
            else:
                if not address.is_global:
                    raise ValueError("Private/local browser addresses are not accepted here.")
        if operation == "search" and (not isinstance(p["query"], str) or not p["query"].strip() or len(p["query"]) > 500):
            raise ValueError("Search needs a short nonempty query.")
        if operation in {"transcribe", "play_media"}:
            self._media(p["path"])
        if operation == "launch_app" and p["application"] not in {"calculator", "notepad"}:
            raise ValueError("Supported launches: calculator, notepad; use approved browser URLs for websites.")
        if operation == "assist" and (not isinstance(p["question"], str) or not p["question"].strip() or len(p["question"]) > 1000):
            raise ValueError("Use a question up to 1000 characters.")
        if operation == "watch":
            from core.screen_observer import LocalScreenVision
            LocalScreenVision(endpoint=p["endpoint"], model=p["model"])
            if type(p["duration"]) is not int or not 10 <= p["duration"] <= 600 or type(p["interval"]) is not int or not 3 <= p["interval"] <= 60:
                raise ValueError("Choose 10–600 seconds and 3–60 seconds between observations.")

    def _media(self, relative):
        if self.media_root is None or not isinstance(relative, str):
            raise ValueError("Connect a media folder first.")
        path = self.media_root / relative
        if Path(relative).is_absolute() or ":" in relative or ".." in Path(relative).parts:
            raise ValueError("Choose media inside the connected folder.")
        for parent in (path, *path.parents):
            if parent == self.media_root:
                break
            if parent.is_symlink() or (hasattr(parent, "is_junction") and parent.is_junction()):
                raise ValueError("Linked media paths are not accepted.")
        path = path.resolve(strict=True)
        if not path.is_relative_to(self.media_root) or not path.is_file() or path.stat().st_size > 500_000_000 or path.suffix.lower() not in {".mp4", ".mkv", ".webm", ".mp3", ".wav", ".m4a", ".ogg", ".flac"}:
            raise ValueError("Choose audio/video up to 500 MB inside the connected folder.")
        return path

    def perform(self, operation, p):
        self.validate(operation, p)
        if operation == "excerpt_summary":
            from core.desktop_requests import excerpt_summary
            return excerpt_summary(p["text"])
        if operation in {"save_correction", "recall_corrections"}:
            from core.desktop_lessons import DesktopLessons
            lessons = DesktopLessons()
            if operation == "save_correction":
                return lessons.save(p["request"], p["correction"], user_confirmed=True)
            return {"corrections": lessons.recall(p["request"]), "executable": False}
        if operation == "discover_video":
            from core.video_sources import discover_video_sources
            return discover_video_sources(p["url"])
        if operation == "youtube_captions":
            from core.youtube_captions import read_youtube_captions
            return read_youtube_captions(p["url"], language=p["language"])
        if operation == "read_document":
            from core.document_reader import read_document
            return read_document(self.media_root, p["path"])
        if operation == "download_media":
            from core.public_media import download_public_media
            return download_public_media(p["url"], self.media_root / "booda-downloads")
        if operation == "inspect_media":
            from core.media_inspection import inspect_media
            return inspect_media(self._media(p["path"]))
        if operation == "ocr_screen":
            from core.image_text import read_image_text
            return read_image_text(self.ui.screenshot())
        if operation.startswith("browser_"):
            from core.browser_tools import ReviewedBrowser
            if self.browser_tools is None:
                self.browser_tools = ReviewedBrowser()
            try:
                if operation == "browser_open":
                    return self.browser_tools.open(p["url"])
                if operation == "browser_read":
                    return self.browser_tools.read()
                return self.browser_tools.act(operation, p)
            except ValueError:
                raise
            except Exception as error:
                raise RuntimeError("تعذر إكمال خطوة المتصفح؛ اقرأ الصفحة وراجعها من جديد.") from error
        if operation == "read_webpage":
            from core.research_web import PublicTextFetcher, source_from_response
            return {**source_from_response(PublicTextFetcher().fetch(p["url"])),
                    "untrusted": True, "browser_session_used": False, "executed": False}
        if operation == "read_captions":
            from core.public_captions import read_public_captions
            return read_public_captions(p["url"])
        if operation == "restore_window":
            import ctypes
            hwnd = ctypes.c_void_p(p["window"])
            self.user32.ShowWindow(hwnd, 9)
            foreground = bool(self.user32.SetForegroundWindow(hwnd))
            return {"window": self._window(p["window"]), "foreground_requested": foreground,
                    "verification_required": True}
        if operation in {"read_elements", "verify_text"}:
            from core.desktop_accessibility import WindowsAccessibility
            target = self.review_target()
            reader = WindowsAccessibility()
            if operation == "verify_text":
                result = reader.verify_text(target["window"], p["expected"])
            else:
                result = reader.read(target["window"])
            if self.review_target() != target:
                raise RuntimeError("تغيرت النافذة أثناء القراءة؛ أعد المراجعة قبل الاعتماد على النتيجة.")
            return result
        if operation == "assist":
            from core.screen_observer import LocalScreenVision
            from core.vision_runtime import ensure_screen_vision
            from core.local_model import ensure_local_model_server
            from core.desktop_assistant import BoodaDesktopAssistant, visual_answer
            image = self.ui.screenshot()
            from core.screen_evidence import read_text_evidence
            text_evidence = read_text_evidence(image)
            captured_at = time.monotonic()
            with ensure_screen_vision() as endpoint:
                description = LocalScreenVision(endpoint=endpoint).describe(image,
                    question="Describe only visible evidence relevant to this user question. Do not perform any action. User question: " + p["question"])
            if p.get("propose", False):
                with ensure_local_model_server():
                    result = BoodaDesktopAssistant().respond(p["question"], description)
            else:
                result = visual_answer(description)
            if result["action"]:
                self.validate(result["action"]["operation"], result["action"]["parameters"])
            return {**result, **text_evidence, "observation": description, "observed_at": captured_at}
        if operation == "observe":
            self.output.mkdir(parents=True, exist_ok=True)
            path = self.output / (uuid.uuid4().hex + ".png")
            self.ui.screenshot().save(path)
            return {"screenshot": str(path), "target": self.target(), "screen": list(self.ui.size())}
        if operation == "watch":
            from core.screen_observer import show_observer
            if p["endpoint"] == "http://127.0.0.1:8081/v1" and p["model"] == "screen-vision":
                from core.vision_runtime import ensure_screen_vision
                with ensure_screen_vision():
                    return show_observer(self.ui.screenshot, **p)
            return show_observer(self.ui.screenshot, **p)
        if operation == "move":
            self.ui.moveTo(p["x"], p["y"], duration=0.2)
        elif operation == "click":
            self.ui.click(p["x"], p["y"], button=p["button"])
        elif operation == "drag":
            self.ui.moveTo(p["x"], p["y"], duration=0.2)
            self.ui.dragTo(p["x2"], p["y2"], duration=0.4)
        elif operation == "scroll":
            self.ui.scroll(p["amount"], x=p["x"], y=p["y"])
        elif operation == "key":
            self.ui.hotkey(*p["key"].split("+"))
        elif operation == "type":
            self._unicode(p["text"])
        elif operation in {"open_url", "search"}:
            import webbrowser
            url = p["url"] if operation == "open_url" else "https://www.google.com/search?q=" + quote_plus(p["query"])
            if not webbrowser.open(url, new=2):
                raise RuntimeError("The default browser did not accept the request.")
            return {"opened": url, "playback_verified": False}
        elif operation == "transcribe":
            from core.media_transcript import transcribe_local
            return transcribe_local(self._media(p["path"]), model_path=self.model_path, output_root=self.output)
        elif operation == "play_media":
            import os
            os.startfile(str(self._media(p["path"])))
            return {"opened": p["path"], "playback_verified": False}
        elif operation == "launch_app":
            import os
            import subprocess
            if p["application"] == "calculator":
                os.startfile("calculator:")
            else:
                executable = Path(os.environ.get("WINDIR", "C:/Windows")) / "System32" / "notepad.exe"
                subprocess.Popen([str(executable)], shell=False)
            return {"launched": p["application"], "verification_required": True}
        return {"input_sent": True, "verification_required": True}

    def _unicode(self, text):
        """Unicode SendInput supports Arabic without modifying the clipboard."""
        import ctypes as c
        from ctypes import wintypes as w
        class Mouse(c.Structure):
            _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD), ("dwFlags", w.DWORD), ("time", w.DWORD), ("extra", c.c_size_t)]
        class Keyboard(c.Structure):
            _fields_ = [("vk", w.WORD), ("scan", w.WORD), ("flags", w.DWORD), ("time", w.DWORD), ("extra", c.c_size_t)]
        class Hardware(c.Structure):
            _fields_ = [("msg", w.DWORD), ("low", w.WORD), ("high", w.WORD)]
        class Union(c.Union):
            _fields_ = [("mi", Mouse), ("ki", Keyboard), ("hi", Hardware)]
        class Input(c.Structure):
            _fields_ = [("type", w.DWORD), ("data", Union)]
        approved_target = self.review_target()
        raw = text.encode("utf-16-le")
        for offset in range(0, len(raw), 2):
            self.ui.failSafeCheck()
            current_target = self.target()
            # Editors update their caption when the approved text changes.
            # Keep the foreground window, process and geometry bound throughout.
            if any(current_target.get(field) != approved_target.get(field)
                   for field in ("window", "pid", "bounds")):
                raise RuntimeError("Window changed during typing; inspect before another request.")
            unit = int.from_bytes(raw[offset:offset + 2], "little")
            down = (Input * 1)(Input(1, Union(ki=Keyboard(0, unit, 4, 0, 0))))
            up = (Input * 1)(Input(1, Union(ki=Keyboard(0, unit, 6, 0, 0))))
            if self.user32.SendInput(1, down, c.sizeof(Input)) != 1:
                raise RuntimeError("Unicode input incomplete; do not retry without inspecting the window.")
            # Do not send a zero-duration VK_PACKET press. Modern editors can
            # consume input asynchronously; keep both the hold and release gap.
            # Always release an accepted press, even if the wait is interrupted.
            try:
                time.sleep(0.05)
            finally:
                if self.user32.SendInput(1, up, c.sizeof(Input)) != 1:
                    raise RuntimeError("Unicode key release incomplete; inspect before another request.")
            time.sleep(0.05)
