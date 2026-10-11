import json
from pathlib import Path

from core.permission import BoodaPermission
from core.persistence import JsonObjectStore


class BoodaPermissionManager:
    def __init__(self, audit_log=None, file_path=None):
        self.permissions = {}
        self.audit_log = audit_log
        self.file_path = Path(file_path) if file_path else None
        self._saved_permissions = self._load_permission_states()

    def _load_permission_states(self):
        if self.file_path is None or not self.file_path.exists():
            return {}

        with self.file_path.open("r", encoding="utf-8") as file:
            saved_permissions = json.load(file)

        if not isinstance(saved_permissions, dict):
            raise ValueError("Permission state file must contain an object.")

        return saved_permissions

    def _save_permission_states(self):
        if self.file_path is None:
            return

        for name, permission in self.permissions.items():
            self._saved_permissions[name] = permission.allowed

        JsonObjectStore(self.file_path).save(self._saved_permissions)

    def add_permission(
        self,
        name,
        category="general",
        risk_level="low",
        allowed=False,
    ):
        if name in self._saved_permissions:
            allowed = self._saved_permissions[name]

        permission = BoodaPermission(
            name=name,
            category=category,
            risk_level=risk_level,
            allowed=allowed,
        )

        self.permissions[name] = permission
        self._save_permission_states()
        return permission

    def get_permission(self, name):
        return self.permissions.get(name)

    def is_allowed(self, name):
        permission = self.get_permission(name)

        if permission is None:
            return False

        return permission.allowed

    def get_by_category(self, category):
        return [
            permission
            for permission in self.permissions.values()
            if permission.category == category
        ]

    def grant_permission(self, name, changed_by=None):
        permission = self.get_permission(name)

        if permission is None:
            self._record_permission_change(
                action="permission_granted",
                name=name,
                changed_by=changed_by,
                outcome="rejected",
                rejection_reason="Permission not found.",
            )
            return False

        previous_allowed = permission.allowed
        previous_saved = dict(self._saved_permissions)
        permission.grant()
        try:
            self._save_permission_states()
        except Exception:
            permission.allowed = previous_allowed
            self._saved_permissions = previous_saved
            raise
        self._record_permission_change(
            action="permission_granted",
            name=name,
            changed_by=changed_by,
            outcome="completed",
        )
        return True

    def revoke_permission(self, name, changed_by=None):
        permission = self.get_permission(name)

        if permission is None:
            self._record_permission_change(
                action="permission_revoked",
                name=name,
                changed_by=changed_by,
                outcome="rejected",
                rejection_reason="Permission not found.",
            )
            return False

        previous_allowed = permission.allowed
        previous_saved = dict(self._saved_permissions)
        permission.revoke()
        try:
            self._save_permission_states()
        except Exception:
            permission.allowed = previous_allowed
            self._saved_permissions = previous_saved
            raise
        self._record_permission_change(
            action="permission_revoked",
            name=name,
            changed_by=changed_by,
            outcome="completed",
        )
        return True

    def _record_permission_change(
        self,
        *,
        action,
        name,
        changed_by,
        outcome,
        rejection_reason=None,
    ):
        if self.audit_log is None:
            return

        self.audit_log.record(
            action=action,
            requested_by=changed_by,
            permission_name=name,
            outcome=outcome,
            rejection_reason=rejection_reason,
        )

