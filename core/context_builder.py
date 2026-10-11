"""Build a structured, precedence-aware context for Booda planners."""

from dataclasses import asdict
import re


_SENSITIVE_KEY = re.compile(
    r"(?:api.?key|secret|token|password|credential|authorization)", re.IGNORECASE
)


def _without_sensitive_fields(value):
    if isinstance(value, dict):
        return {
            key: _without_sensitive_fields(item)
            for key, item in value.items()
            if not _SENSITIVE_KEY.search(str(key))
        }
    if isinstance(value, list):
        return [_without_sensitive_fields(item) for item in value]
    return value


class BoodaContextBuilder:
    """Combine goal memory with the active profile and applicable preferences."""

    INSTRUCTION_PRIORITY = (
        "قيود النظام والسلامة والصلاحيات ومخطط الخرج",
        "طلب المستخدم الحالي والهدف المحدد",
        "التفضيلات الصريحة، ثم الأضيق نطاقًا عند تساوي المصدر",
        "التفضيلات المستوردة",
        "التفضيلات المستنتجة",
        "القيم الافتراضية في الملف الشخصي والنظام",
    )

    def __init__(self, profile_manager):
        if profile_manager is None:
            raise ValueError("A user profile manager is required.")
        self.profile_manager = profile_manager

    def build(self, goal, memory=None, *, task_id=None):
        if goal is None:
            raise ValueError("A goal is required to build user context.")
        user_id = goal.context.get("user_id") or self.profile_manager.default_user_id
        profile = self.profile_manager.get_profile(user_id)
        if profile is None:
            raise ValueError(f"Unknown user profile: {user_id}")
        preferences = self.profile_manager.effective_preferences(
            user_id,
            project_id=goal.context.get("project_id"),
            task_id=task_id,
        )
        safe_profile = _without_sensitive_fields(asdict(profile))
        preference_values = {
            key: _without_sensitive_fields(item.value)
            for key, item in preferences.items()
            if not _SENSITIVE_KEY.search(key)
        }
        preference_sources = {
            key: {
                "source": item.source,
                "scope": item.scope,
                "scope_id": item.scope_id,
                "confidence": item.confidence,
                "preference_type": item.preference_type,
                "updated_at": item.updated_at,
            }
            for key, item in preferences.items()
            if not _SENSITIVE_KEY.search(key)
        }
        language = preference_values.get("language", profile.language)
        response_style = preference_values.get(
            "response_style", profile.response_style
        )
        learning_preferences = preference_values.get(
            "learning_preferences", safe_profile["learning_preferences"]
        )
        context = dict(memory) if isinstance(memory, dict) else {}
        if memory is not None and not isinstance(memory, dict):
            context["prior_memory"] = memory
        context.update({
            "user_profile": safe_profile,
            "user_preferences": preference_values,
            "preference_sources": preference_sources,
            "instructions": {
                "priority": list(self.INSTRUCTION_PRIORITY),
                "language": _without_sensitive_fields(language),
                "response_style": _without_sensitive_fields(response_style),
                "learning_preferences": _without_sensitive_fields(
                    learning_preferences
                ),
            },
        })
        return context
