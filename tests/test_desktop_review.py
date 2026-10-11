from types import SimpleNamespace
from core.desktop_review import request_preview


def test_arabic_preview_contains_exact_action_text_and_window():
    task = SimpleNamespace(metadata={"operation": "type", "parameters": {"text": "نص عربي للمراجعة"},
        "target": {"title": "Untitled - Notepad"}})
    preview = request_preview(task)
    assert "كتابة نص" in preview
    assert "نص عربي للمراجعة" in preview
    assert "Untitled - Notepad" in preview
    assert "موافقة جديدة" in preview
