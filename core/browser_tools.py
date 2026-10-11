"""Isolated browser session. The desktop controller approves each call separately."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import socket
import time
import uuid
from urllib.parse import urlsplit

from core.research_web import public_url


def check_public_address(url):
    url = public_url(url)
    addresses = socket.getaddrinfo(urlsplit(url).hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError("المتصفح يقبل مواقع HTTPS العامة فقط.")
    return url


class ReviewedBrowser:
    def __init__(self, page=None):
        self.page = page
        self.runtime = self.browser = None
        self.snapshot = None

    def _start(self):
        if self.page is not None:
            return
        from playwright.sync_api import sync_playwright
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(Path(__file__).resolve().parents[1] / ".local-ai-runtime/browsers")
        self.runtime = sync_playwright().start()
        try:
            self.browser = self.runtime.chromium.launch(headless=False)
            context = self.browser.new_context(accept_downloads=False, service_workers="block")
            def route(request_route):
                try:
                    check_public_address(request_route.request.url)
                except (ValueError, OSError):
                    request_route.abort()
                else:
                    request_route.continue_()
            context.route("**/*", route)
            self.page = context.new_page()
            self.page.set_default_timeout(5000)
            # Popups do not become implicit approved targets.
            context.on("page", lambda page: page.close() if page != self.page else None)
        except Exception:
            self.close()
            raise

    def close(self):
        self.snapshot = None
        try:
            if self.browser:
                self.browser.close()
        finally:
            if self.runtime:
                self.runtime.stop()
            self.page = self.browser = self.runtime = None

    def _state(self):
        elements = []
        for role in ("button", "link", "textbox"):
            for item in self.page.get_by_role(role).all()[:60]:
                if not item.is_visible():
                    continue
                if role == "textbox" and (item.get_attribute("type") or "").lower() == "password":
                    continue
                name = item.get_attribute("aria-label") or item.inner_text() or item.get_attribute("placeholder") or ""
                if name.strip():
                    elements.append({"role": role, "name": name.strip()[:200]})
        state = {"url": self.page.url, "title": self.page.title(),
                 "text": self.page.locator("body").inner_text()[:20000], "elements": elements[:120]}
        return state

    def read(self):
        if self.page is None:
            raise ValueError("افتح صفحة في متصفح بودا أولًا.")
        state = self._state()
        token = uuid.uuid4().hex
        self.snapshot = (token, self._digest(state), state["elements"], time.monotonic())
        return {**state, "snapshot": token, "untrusted": True, "requires_review": True}

    @staticmethod
    def _digest(state):
        return hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def open(self, url):
        url = check_public_address(url)
        self.snapshot = None
        self._start()
        self.page.goto(url, wait_until="domcontentloaded", timeout=20000)
        return self.read()

    def act(self, operation, parameters):
        previous, self.snapshot = self.snapshot, None
        if previous is None or parameters["snapshot"] != previous[0] or time.monotonic() - previous[3] > 60:
            raise ValueError("اقرأ الصفحة مجددًا؛ موافقة العنصر تحتاج لقطة حديثة.")
        if self._digest(self._state()) != previous[1]:
            raise ValueError("تغيرت الصفحة؛ اقرأها وراجع العنصر من جديد.")
        target = {"role": parameters["role"], "name": parameters["name"]}
        if target not in previous[2]:
            raise ValueError("العنصر غير موجود في القراءة المعروضة.")
        item = self.page.get_by_role(target["role"], name=target["name"], exact=True)
        if item.count() != 1 or not item.is_visible() or not item.is_enabled():
            raise ValueError("العنصر غير واضح أو مكرر أو غير متاح.")
        if (item.get_attribute("type") or "").lower() == "password":
            raise ValueError("أدخل بيانات الدخول بنفسك.")
        if operation == "browser_fill":
            if target["role"] != "textbox":
                raise ValueError("الكتابة تحتاج مربع نص.")
            item.fill(parameters["text"])
        else:
            if target["role"] not in {"button", "link"}:
                raise ValueError("النقر يحتاج زرًا أو رابطًا.")
            item.click(no_wait_after=True)
        return {"action_sent": True, "verification_required": True,
                "message": "اقرأ الصفحة بعد التنفيذ للتحقق من النتيجة."}
