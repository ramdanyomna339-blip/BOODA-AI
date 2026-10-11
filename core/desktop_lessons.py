"""Reviewed desktop corrections are recalled as data, never as action permissions."""
import hashlib
import re
from core.memory import BoodaStructuredMemoryStore


class DesktopLessons:
    def __init__(self, path="memory/desktop_lessons.sqlite3"):
        self.store = BoodaStructuredMemoryStore(path)

    def save(self, request, correction, *, user_confirmed=False):
        if not user_confirmed:
            raise PermissionError("حفظ التصحيح يحتاج موافقة صريحة.")
        if not isinstance(request, str) or not request.strip() or len(request) > 1000:
            raise ValueError("حدد الطلب الذي تصححه حتى 1000 حرف.")
        if not isinstance(correction, str) or not correction.strip() or len(correction) > 1000:
            raise ValueError("اكتب التصحيح حتى 1000 حرف.")
        key = "desktop-correction-" + hashlib.sha256(request.strip().encode()).hexdigest()
        current = [entry for entry in self.store.list_entries(status="approved") if entry["memory_key"] == key]
        value = {"request": request.strip(), "correction": correction.strip()}
        if current:
            return self.store.correct(current[0]["entry_id"], value, rationale="تصحيح صريح من المستخدم", user_confirmed=True)
        return self.store.add_confirmed("lesson", key, value, rationale="تصحيح صريح من المستخدم",
                                        source="desktop-user-correction", user_confirmed=True)

    def recall(self, request):
        key = "desktop-correction-" + hashlib.sha256(request.strip().encode()).hexdigest()
        terms = set(re.findall(r"\w+", request.casefold()))
        result = []
        for row in self.store.list_entries(status="approved"):
            previous = set(re.findall(r"\w+", row["value"]["request"].casefold()))
            score = len(terms & previous) / max(1, len(terms | previous))
            if row["memory_key"] == key or score >= .6:
                result.append({"correction": row["value"]["correction"], "executable": False,
                               "similarity": score, "source": "user-approved-correction"})
        return sorted(result, key=lambda row: row["similarity"], reverse=True)[:5]
