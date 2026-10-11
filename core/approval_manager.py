from datetime import datetime
from pathlib import Path

from core.approval import BoodaApproval
from core.approval_store import BoodaApprovalStore


class BoodaApprovalManager:
    def __init__(self, audit_log=None, file_path=None):
        self.approvals = {}
        self.audit_log = audit_log
        self.file_path = Path(file_path) if file_path else None
        database_path = (
            str(self.file_path) + ".sqlite3"
            if self.file_path is not None
            else ":memory:"
        )
        self._store = BoodaApprovalStore(
            database_path,
            legacy_path=self.file_path,
        )
        self._load_approvals()

    def _bind_approval(self, approval):
        approval._store = self._store
        approval._on_change = lambda approval=approval: self._save_approval(
            approval
        )

    def _load_approvals(self):
        for data in self._store.load_all():
            expires_at = data["expires_at"]
            if expires_at is not None:
                expires_at = datetime.fromisoformat(expires_at)

            approval = BoodaApproval(
                permission_name=data["permission_name"],
                approved_by=data["approved_by"],
                reason=data["reason"],
                task_id=data["task_id"],
                expires_at=expires_at,
                is_approved=bool(data["is_approved"]),
                used=bool(data["used"]),
            )
            approval.approval_id = data["approval_id"]
            approval.execution_status = data["status"]
            approval.execution_id = data["execution_id"]
            self.approvals[approval.approval_id] = approval
            self._bind_approval(approval)

    def _next_approval_id(self):
        used_ids = set(self.approvals)

        if self.audit_log is not None:
            get_events = getattr(self.audit_log, "get_events", None)

            if callable(get_events):
                for event in get_events() or []:
                    if isinstance(event, dict):
                        approval_id = event.get("approval_id")
                    else:
                        approval_id = getattr(event, "approval_id", None)

                    if approval_id:
                        used_ids.add(str(approval_id))

        number = self._store.next_id(used_ids)
        candidate = f"approval-{number}"
        while candidate in used_ids:
            number += 1
            candidate = f"approval-{number}"
        return candidate

    def _save_approval(self, approval):
        self._store.save_approval(approval)

    def _save_approvals(self):
        for approval in self.approvals.values():
            self._save_approval(approval)

    def create_approval(
        self,
        permission_name,
        approved_by,
        reason="",
        task_id=None,
        expires_in_minutes=None,
        created_by=None,
    ):
        approval_id = self._next_approval_id()

        approval = BoodaApproval(
            permission_name=permission_name,
            approved_by=approved_by,
            reason=reason,
            task_id=task_id,
            expires_in_minutes=expires_in_minutes,
        )
        approval.approval_id = approval_id
        approval.execution_status = "pending"
        approval.execution_id = None
        self._store.create(approval_id, approval)
        self.approvals[approval_id] = approval
        self._bind_approval(approval)

        if self.audit_log is not None:
            self.audit_log.record(
                action="approval_created",
                task_id=approval.task_id,
                requested_by=created_by,
                permission_name=approval.permission_name,
                approval_id=approval_id,
                outcome="completed",
            )

        return approval_id, approval

    def get_approval(self, approval_id):
        return self.approvals.get(approval_id)

    def approve_approval(self, approval_id, approved_by=None):
        approval = self.get_approval(approval_id)

        if approval is None:
            self._record_missing_approval(
                action="approval_granted",
                approval_id=approval_id,
                changed_by=approved_by,
            )
            return False

        if approved_by is not None:
            approval.approved_by = approved_by

        approval.approve()

        if self.audit_log is not None:
            self.audit_log.record(
                action="approval_granted",
                task_id=approval.task_id,
                requested_by=approval.approved_by,
                permission_name=approval.permission_name,
                approval=approval,
                approval_id=approval_id,
                outcome="completed",
            )

        return True

    def revoke_approval(self, approval_id, revoked_by=None):
        approval = self.get_approval(approval_id)

        if approval is None:
            self._record_missing_approval(
                action="approval_revoked",
                approval_id=approval_id,
                changed_by=revoked_by,
            )
            return False

        approval.revoke()

        if self.audit_log is not None:
            self.audit_log.record(
                action="approval_revoked",
                task_id=approval.task_id,
                requested_by=revoked_by or approval.approved_by,
                permission_name=approval.permission_name,
                approval=approval,
                approval_id=approval_id,
                outcome="completed",
            )

        return True

    def _record_missing_approval(self, *, action, approval_id, changed_by):
        if self.audit_log is None:
            return

        self.audit_log.record(
            action=action,
            requested_by=changed_by,
            approval_id=approval_id,
            outcome="rejected",
            rejection_reason="Approval not found.",
        )
