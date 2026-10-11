from datetime import datetime, timedelta
from threading import Lock
from uuid import uuid4


class BoodaApproval:
    def __init__(
        self,
        permission_name,
        approved_by,
        reason="",
        task_id=None,
        expires_in_minutes=None,
        expires_at=None,
        is_approved=False,
        used=False,
    ):
        self.permission_name = permission_name
        self.approved_by = approved_by
        self.reason = reason
        self.task_id = task_id
        self.is_approved = is_approved
        self.used = used
        self.approval_id = None
        self._on_change = None
        self._store = None
        self._state_lock = Lock()
        self.execution_status = "pending"
        self.execution_id = None

        if expires_at is not None:
            self.expires_at = expires_at
        elif expires_in_minutes is not None:
            self.expires_at = (
                datetime.now() + timedelta(minutes=expires_in_minutes)
            )
        else:
            self.expires_at = None

    def _save_state(self):
        if self._on_change is not None:
            self._on_change()

    def approve(self):
        with self._state_lock:
            self.is_approved = True
            self._save_state()

    def revoke(self):
        with self._state_lock:
            self.is_approved = False
            self._save_state()

    def mark_used(self):
        with self._state_lock:
            self.used = True
            if self.execution_status in {"pending", "available", "revoked"}:
                self.execution_status = "uncertain"
            self._save_state()

    def claim_use(self, *, permission_name, task_id):
        """Atomically validate and persist this approval's one-time use."""
        with self._state_lock:
            if self.is_approved is not True:
                return "Approval not granted."
            if self.permission_name != permission_name:
                return "Approval does not match permission."
            if self.task_id != task_id:
                return "Approval does not match task."
            if self.is_expired():
                return "Approval expired."
            if self.used is not False:
                return "Approval already used."

            execution_id = str(uuid4())
            if self._store is not None:
                return self._store.claim_use(
                    self,
                    permission_name=permission_name,
                    task_id=task_id,
                    execution_id=execution_id,
                )

            self.used = True
            self.execution_id = execution_id
            self.execution_status = "reserved"
            self._save_state()
            return None

    def start_execution(self):
        if self._store is not None:
            return self._store.transition_execution(self, "executing")
        if self.execution_status != "reserved":
            raise RuntimeError("Approval is not reserved for execution.")
        self.execution_status = "executing"
        self._save_state()
        return self.execution_status

    def finish_execution(self, status, *, detail=None):
        if self._store is not None:
            return self._store.transition_execution(
                self,
                status,
                detail=detail,
            )
        if status not in {"completed", "failed", "uncertain"}:
            raise ValueError(f"Invalid execution status: {status}")
        if self.execution_status not in {"reserved", "executing"}:
            raise RuntimeError("Approval has no active execution.")
        self.execution_status = status
        self._save_state()
        return self.execution_status

    def is_expired(self):
        if self.expires_at is None:
            return False

        return datetime.now() >= self.expires_at