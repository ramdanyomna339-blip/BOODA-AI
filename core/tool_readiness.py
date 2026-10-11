"""Dependency inspection without screen capture or launching applications."""
import importlib.util
from pathlib import Path


def inspect_tools(root=None):
    root = Path(root or Path(__file__).resolve().parents[1])
    runtime = root / ".local-ai-runtime"
    packages = {"الماوس والكيبورد": "pyautogui", "عناصر النوافذ": "pywinauto",
                "المتصفح": "playwright", "قراءة العربية من الصور": "tesserocr",
                "تفريغ الصوت": "faster_whisper", "قراءة ملفات الوسائط": "av"}
    packages.update({"قراءة PDF": "pypdf", "قراءة Excel": "openpyxl", "قراءة Word XML": "defusedxml"})
    packages["ترجمة YouTube المتاحة"] = "youtube_transcript_api"
    rows = [{"tool": label, "installed": importlib.util.find_spec(package) is not None}
            for label, package in packages.items()]
    rows += [{"tool": "بيانات OCR عربي وإنجليزي", "installed": all(
        (runtime / "tessdata" / (lang + ".traineddata")).is_file() for lang in ("ara", "eng"))},
        {"tool": "متصفح Chromium المحلي", "installed": any(
            (runtime / "browsers").glob("chromium-*/chrome-win*/chrome.exe"))}]
    return {"tools": rows, "live_tested": False,
            "message": "التثبيت لا يثبت نجاح الاستخدام الحي؛ إجراءات الشاشة والمتصفح تحتاج موافقتك."}
