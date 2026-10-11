"""Local user profiles and scoped preferences."""

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
import json
import math
from typing import Any
from uuid import uuid4

from core.persistence import JsonObjectStore


PREFERENCE_SCOPES = {"user", "project", "task"}
PREFERENCE_SOURCES = {"explicit", "inferred", "system", "imported"}
PREFERENCE_TYPES = {"persistent", "temporary"}
DEFAULT_USER_ID = "local-user"


def _now():
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class UserProfile:
    user_id: str
    display_name: str | None = None
    language: str = "ar-EG"
    timezone: str | None = None
    response_style: str = "Egyptian colloquial Arabic"
    learning_preferences: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


@dataclass(frozen=True)
class Preference:
    id: str
    user_id: str
    key: str
    value: Any
    scope: str
    scope_id: str
    source: str
    confidence: float
    preference_type: str
    active: bool
    created_at: str
    updated_at: str
    updated_by: str | None = None


class BoodaUserProfileManager:
    """Persist local profiles and preferences without requiring authentication."""

    def __init__(
        self,
        file_path="memory/user_profile.json",
        *,
        audit_log=None,
        event_log=None,
        default_user_id=DEFAULT_USER_ID,
    ):
        self.store = JsonObjectStore(file_path)
        self.audit_log = audit_log
        self.event_log = event_log
        self.default_user_id = self._require_text(default_user_id, "user_id")
        self.data = self.store.load()
        self.data.setdefault("profiles", {})
        self.data.setdefault("preferences", {})
        if self.default_user_id not in self.data["profiles"]:
            now = _now()
            self.data["profiles"][self.default_user_id] = asdict(
                UserProfile(
                    user_id=self.default_user_id,
                    created_at=now,
                    updated_at=now,
                )
            )
            self._add_default_preferences(now)
            self._save()

    @staticmethod
    def _require_text(value, field_name):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must not be empty.")
        return value.strip()

    def _save(self):
        self.store.save(self.data)

    def _add_default_preferences(self, timestamp):
        defaults = {
            "language": "ar-EG",
            "response_style": "Egyptian colloquial Arabic",
            "avoid_unrequested_age_restriction_labels": True,
        }
        for key, value in defaults.items():
            preference = Preference(
                id=f"preference-{uuid4().hex}",
                user_id=self.default_user_id,
                key=key,
                value=value,
                scope="user",
                scope_id=self.default_user_id,
                source="system",
                confidence=1.0,
                preference_type="persistent",
                active=True,
                created_at=timestamp,
                updated_at=timestamp,
                updated_by="system",
            )
            self.data["preferences"][preference.id] = asdict(preference)

    def get_profile(self, user_id=None):
        user_id = user_id or self.default_user_id
        data = self.data["profiles"].get(user_id)
        return UserProfile(**data) if data is not None else None

    def update_profile(self, user_id=None, *, updated_by="user", **changes):
        user_id = user_id or self.default_user_id
        current = self.get_profile(user_id)
        if current is None:
            raise ValueError(f"Unknown user profile: {user_id}")
        allowed = {
            "display_name", "language", "timezone", "response_style",
            "learning_preferences",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"Unsupported profile fields: {', '.join(sorted(unknown))}")
        if not changes:
            return current
        if changes.get("display_name") is not None:
            changes["display_name"] = self._require_text(
                changes["display_name"], "display_name"
            )
        for field_name in ("language", "response_style"):
            if field_name in changes:
                changes[field_name] = self._require_text(
                    changes[field_name], field_name
                )
        if "timezone" in changes and changes["timezone"] is not None:
            changes["timezone"] = self._require_text(
                changes["timezone"], "timezone"
            )
        if "learning_preferences" in changes:
            if not isinstance(changes["learning_preferences"], dict):
                raise ValueError("learning_preferences must be an object.")
            self._validate_json_value(changes["learning_preferences"])
            changes["learning_preferences"] = dict(changes["learning_preferences"])
        updated = replace(current, updated_at=_now(), **changes)
        self.data["profiles"][user_id] = asdict(updated)
        for field_name in ("language", "response_style"):
            if field_name not in changes:
                continue
            preference = next((
                item for item in self.data["preferences"].values()
                if item["user_id"] == user_id
                and item["key"] == field_name
                and item["scope"] == "user"
                and item["scope_id"] == user_id
                and item["source"] == "system"
                and item["preference_type"] == "persistent"
            ), None)
            if preference is not None:
                preference["value"] = changes[field_name]
                preference["updated_at"] = updated.updated_at
        self._save()
        self._record(
            "user_profile_updated",
            user_id,
            "User profile updated",
            updated_by,
            {"fields": sorted(changes)},
        )
        return updated

    def set_preference(
        self,
        key,
        value,
        *,
        user_id=None,
        scope="user",
        scope_id=None,
        source="explicit",
        confidence=1.0,
        preference_type="persistent",
        active=True,
        updated_by="user",
    ):
        user_id = user_id or self.default_user_id
        self._require_text(user_id, "user_id")
        key = self._require_text(key, "key")
        if scope not in PREFERENCE_SCOPES:
            raise ValueError(f"Invalid preference scope: {scope}")
        if source not in PREFERENCE_SOURCES:
            raise ValueError(f"Invalid preference source: {source}")
        if preference_type not in PREFERENCE_TYPES:
            raise ValueError(f"Invalid preference type: {preference_type}")
        if not isinstance(active, bool):
            raise ValueError("active must be a boolean.")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            raise ValueError("confidence must be between 0 and 1.")
        if scope == "user":
            if scope_id not in (None, user_id):
                raise ValueError("User-scoped preferences must use the user id as scope_id.")
            scope_id = user_id
        else:
            scope_id = self._require_text(scope_id, "scope_id")
        self._validate_json_value(value)

        existing = next((
            item for item in self.data["preferences"].values()
            if item["user_id"] == user_id
            and item["key"] == key
            and item["scope"] == scope
            and item["scope_id"] == scope_id
            and item["preference_type"] == preference_type
        ), None)
        now = _now()
        preference = Preference(
            id=existing["id"] if existing else f"preference-{uuid4().hex}",
            user_id=user_id,
            key=key,
            value=value,
            scope=scope,
            scope_id=scope_id,
            source=source,
            confidence=float(confidence),
            preference_type=preference_type,
            active=active,
            created_at=existing["created_at"] if existing else now,
            updated_at=now,
            updated_by=updated_by,
        )
        self.data["preferences"][preference.id] = asdict(preference)
        self._save()
        self._record(
            "preference_updated" if existing else "preference_created",
            preference.id,
            f"Preference {key}",
            updated_by,
            {"user_id": user_id, "key": key, "scope": scope, "scope_id": scope_id},
        )
        return preference

    def list_preferences(self, user_id=None, *, include_inactive=False):
        user_id = user_id or self.default_user_id
        return [
            Preference(**item)
            for item in self.data["preferences"].values()
            if item["user_id"] == user_id
            and (include_inactive or item["active"])
        ]

    def get_preference(self, preference_id):
        data = self.data["preferences"].get(preference_id)
        return Preference(**data) if data is not None else None

    def deactivate_preference(self, preference_id, *, updated_by="user"):
        current = self.get_preference(preference_id)
        if current is None:
            return None
        if not current.active:
            return current
        updated = replace(current, active=False, updated_at=_now(), updated_by=updated_by)
        self.data["preferences"][preference_id] = asdict(updated)
        self._save()
        self._record(
            "preference_deactivated",
            preference_id,
            f"Preference {current.key}",
            updated_by,
            {"user_id": current.user_id, "key": current.key},
        )
        return updated

    def activate_preference(self, preference_id, *, updated_by="user"):
        current = self.get_preference(preference_id)
        if current is None or current.active:
            return current
        updated = replace(current, active=True, updated_at=_now(), updated_by=updated_by)
        self.data["preferences"][preference_id] = asdict(updated)
        self._save()
        self._record(
            "preference_activated",
            preference_id,
            f"Preference {current.key}",
            updated_by,
            {"user_id": current.user_id, "key": current.key},
        )
        return updated

    def promote_preference(self, preference_id, *, updated_by="user"):
        current = self.get_preference(preference_id)
        if current is None:
            return None
        if current.source not in {"imported", "inferred"}:
            raise ValueError("Only imported or inferred preferences can be accepted.")
        updated = replace(
            current,
            source="explicit",
            active=True,
            updated_at=_now(),
            updated_by=updated_by,
        )
        self.data["preferences"][preference_id] = asdict(updated)
        self._save()
        self._record(
            "preference_promoted",
            preference_id,
            f"Preference {current.key}",
            updated_by,
            {
                "user_id": current.user_id,
                "key": current.key,
                "previous_source": current.source,
                "source": "explicit",
            },
        )
        return updated

    def delete_preference(self, preference_id, *, updated_by="user"):
        current = self.get_preference(preference_id)
        if current is None:
            return None
        del self.data["preferences"][preference_id]
        self._save()
        self._record(
            "preference_deleted",
            preference_id,
            f"Preference {current.key}",
            updated_by,
            {
                "user_id": current.user_id,
                "key": current.key,
                "scope": current.scope,
                "scope_id": current.scope_id,
            },
        )
        return current

    def effective_preferences(self, user_id=None, *, project_id=None, task_id=None):
        user_id = user_id or self.default_user_id
        applicable = []
        for item in self.data["preferences"].values():
            if item["user_id"] != user_id or not item["active"]:
                continue
            if item["scope"] == "user" and item["scope_id"] == user_id:
                scope_rank = 1
            elif (
                item["scope"] == "project"
                and project_id is not None
                and item["scope_id"] == project_id
            ):
                scope_rank = 2
            elif (
                item["scope"] == "task"
                and task_id is not None
                and item["scope_id"] == task_id
            ):
                scope_rank = 3
            else:
                continue
            source_rank = {
                "system": 1,
                "inferred": 2,
                "imported": 3,
                "explicit": 4,
            }[item["source"]]
            temporary_rank = int(item["preference_type"] == "temporary")
            applicable.append((
                source_rank,
                scope_rank,
                temporary_rank,
                item["updated_at"],
                item,
            ))
        applicable.sort(key=lambda ranked: ranked[:4], reverse=True)
        effective = {}
        for _, _, _, _, item in applicable:
            effective.setdefault(item["key"], Preference(**item))
        return effective

    @staticmethod
    def _validate_json_value(value):
        try:
            json.dumps(value, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError("Preference values must be valid JSON data.") from error

    def _record(self, action, entity_id, title, actor, details):
        if self.audit_log is not None:
            self.audit_log.record(
                action=action,
                task_id=entity_id,
                task_title=title,
                requested_by=actor,
                outcome="completed",
            )
        if self.event_log is not None:
            self.event_log.record(
                action,
                entity_type="user_profile" if action.startswith("user_profile") else "preference",
                entity_id=entity_id,
                details=details,
            )
