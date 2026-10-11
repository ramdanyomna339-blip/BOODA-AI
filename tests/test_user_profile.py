import json

import pytest

from core.audit_log import BoodaAuditLog
from core.event_log import BoodaEventLog
from core.user_profile import BoodaUserProfileManager


def test_default_profile_and_preferences_persist_as_utf8_json(tmp_path):
    path = tmp_path / "memory" / "user_profile.json"
    audit = BoodaAuditLog(tmp_path / "audit.jsonl")
    events = BoodaEventLog(tmp_path / "events.jsonl")
    manager = BoodaUserProfileManager(
        path, audit_log=audit, event_log=events
    )

    profile = manager.get_profile()
    stored_text = path.read_text(encoding="utf-8")
    restored = BoodaUserProfileManager(path)

    assert profile.user_id == "local-user"
    assert profile.language == "ar-EG"
    assert profile.response_style == "Egyptian colloquial Arabic"
    assert profile.display_name is None
    assert json.loads(stored_text)["profiles"]["local-user"]["language"] == "ar-EG"
    assert {
        item.key: item.value for item in restored.list_preferences()
    } == {
        "language": "ar-EG",
        "response_style": "Egyptian colloquial Arabic",
        "avoid_unrequested_age_restriction_labels": True,
    }


def test_profile_and_preference_updates_are_audited_and_reopen(tmp_path):
    path = tmp_path / "profile.json"
    audit = BoodaAuditLog(tmp_path / "audit.jsonl")
    events = BoodaEventLog(tmp_path / "events.jsonl")
    manager = BoodaUserProfileManager(path, audit_log=audit, event_log=events)

    profile = manager.update_profile(
        display_name="يمنى",
        learning_preferences={"format": "hands-on"},
        updated_by="user",
    )
    preference = manager.set_preference(
        "response_style",
        "عربي مصري مختصر",
        updated_by="user",
    )
    updated = manager.set_preference(
        "response_style",
        "عربي مصري واضح",
        updated_by="user",
    )

    reopened = BoodaUserProfileManager(path)
    assert profile.display_name == "يمنى"
    assert profile.learning_preferences == {"format": "hands-on"}
    assert updated.id == preference.id
    assert reopened.get_profile().display_name == "يمنى"
    assert reopened.get_preference(preference.id).value == "عربي مصري واضح"
    assert {event.action for event in audit.get_events()} == {
        "user_profile_updated", "preference_updated"
    }
    assert events.get_events(entity_type="preference")


def test_preference_precedence_and_deactivation(tmp_path):
    manager = BoodaUserProfileManager(tmp_path / "profile.json")
    manager.set_preference(
        "tone", "مستنتج", source="inferred", confidence=0.8
    )
    explicit_user = manager.set_preference(
        "tone", "صريح للمستخدم", source="explicit"
    )
    project = manager.set_preference(
        "tone",
        "صريح للمشروع",
        scope="project",
        scope_id="project-1",
        source="explicit",
    )
    temporary_task = manager.set_preference(
        "tone",
        "مؤقت للمهمة",
        scope="task",
        scope_id="task-1",
        source="explicit",
        preference_type="temporary",
    )

    effective = manager.effective_preferences(
        project_id="project-1", task_id="task-1"
    )
    assert effective["tone"].value == "مؤقت للمهمة"

    manager.deactivate_preference(temporary_task.id)
    effective = manager.effective_preferences(
        project_id="project-1", task_id="task-1"
    )
    assert effective["tone"].value == "صريح للمشروع"
    assert manager.get_preference(temporary_task.id).active is False
    assert explicit_user.active is True
    assert project.id in {
        item.id for item in manager.list_preferences()
    }


def test_profile_field_updates_change_only_the_default_preference(tmp_path):
    manager = BoodaUserProfileManager(tmp_path / "profile.json")
    manager.update_profile(response_style="مصري واضح")
    assert manager.effective_preferences()["response_style"].value == "مصري واضح"

    explicit = manager.set_preference("language", "fr-FR", source="explicit")

    manager.update_profile(language="ar")

    preferences = manager.effective_preferences()
    assert manager.get_profile().language == "ar"
    assert preferences["language"].value == "fr-FR"
    assert manager.get_preference(explicit.id).source == "explicit"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"scope": "organization"}, "scope"),
        ({"source": "guessed"}, "source"),
        ({"preference_type": "session"}, "preference type"),
        ({"confidence": 1.1}, "confidence"),
        ({"scope": "project"}, "scope_id"),
    ],
)
def test_invalid_preferences_are_rejected(tmp_path, kwargs, message):
    manager = BoodaUserProfileManager(tmp_path / "profile.json")

    with pytest.raises(ValueError, match=message):
        manager.set_preference("format", "concise", **kwargs)
