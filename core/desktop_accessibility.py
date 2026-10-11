"""Bounded public UI Automation reads; no execution of screen instructions."""


class WindowsAccessibility:
    def __init__(self, *, desktop=None):
        if desktop is None:
            try:
                from pywinauto import Desktop
            except ImportError as error:
                raise RuntimeError("ثبّت متطلبات التحكم الجديدة لقراءة عناصر النافذة.") from error
            desktop = Desktop(backend="uia")
        self.desktop = desktop

    def read(self, hwnd):
        try:
            return self._read(hwnd)
        except Exception:
            raise RuntimeError("تعذرت قراءة عناصر النافذة؛ قد تكون تغيرت أو لا تدعم القراءة. لم يتم تنفيذ إدخال.") from None

    def _read(self, hwnd):
        root = self.desktop.window(handle=hwnd).wrapper_object()
        # A bounded tree walk avoids materializing every descendant of a large app.
        pending = [(root, 0)]
        rows = []
        while pending and len(rows) < 150:
            element, depth = pending.pop()
            info = element.element_info
            try:
                password = bool(info.element.CurrentIsPassword)
                offscreen = bool(info.element.CurrentIsOffscreen)
            except Exception:
                # Unknown protection state is never treated as readable.
                continue
            if password or offscreen:
                continue
            kind = str(info.control_type)
            name = str(info.name or "")[:200]
            text = ""
            if kind in {"Edit", "Document"}:
                try:
                    text = element.iface_text.DocumentRange.GetText(2000)
                except Exception:
                    try:
                        text = element.iface_value.CurrentValue[:2000]
                    except Exception:
                        pass
            rows.append({"name": name, "type": kind, "text": text,
                         "automation_id": str(info.automation_id or "")[:150]})
            if depth < 6:
                pending.extend((child, depth + 1) for child in element.children()[:30])
        return {"elements": rows, "bounded": True, "untrusted": True,
                "method": "windows_ui_automation", "executed": False}

    def verify_text(self, hwnd, expected):
        observation = self.read(hwnd)
        matches = [row for row in observation["elements"]
                   if row["type"] in {"Edit", "Document"} and expected in row["text"]]
        return {"verified": bool(matches), "expected": expected,
                "method": "exact_text_in_accessible_editor", "executed": False,
                "limit": "Only accessible bounded editor text; this does not prove saving or task completion."}
