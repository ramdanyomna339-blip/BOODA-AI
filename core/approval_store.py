"""Transactional SQLite storage for approvals and their execution lifecycle."""

import json
import hashlib
import os
import sqlite3
import ctypes
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4


class BoodaApprovalStore:
    def __init__(self, database_path, *, legacy_path=None):
        self.database_path = (
            Path(database_path) if database_path != ":memory:" else None
        )
        self.legacy_path = Path(legacy_path) if legacy_path is not None else None
        self._lock = RLock()
        self._memory_connection = None
        if self.database_path is None:
            self._memory_connection = sqlite3.connect(
                ":memory:", check_same_thread=False, isolation_level=None,
                timeout=30,
            )
            self._memory_connection.row_factory = sqlite3.Row
        else:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)

        self._initialize()
        self._import_legacy_if_needed()
        self._recover_interrupted_executions()

    @contextmanager
    def _connection(self):
        connection = self._memory_connection
        close_connection = connection is None
        if close_connection:
            connection = sqlite3.connect(
                str(self.database_path),
                isolation_level=None,
                timeout=30,
            )
            connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA synchronous = FULL")
        try:
            yield connection
        finally:
            if close_connection:
                connection.close()

    @contextmanager
    def _transaction(self):
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _initialize(self):
        with self._transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    permission_name TEXT NOT NULL,
                    approved_by TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    task_id TEXT,
                    is_approved INTEGER NOT NULL CHECK (is_approved IN (0, 1)),
                    used INTEGER NOT NULL CHECK (used IN (0, 1)),
                    expires_at TEXT,
                    status TEXT NOT NULL,
                    execution_id TEXT,
                    executor_pid INTEGER,
                    updated_at TEXT NOT NULL,
                    CHECK (status IN (
                        'pending', 'available', 'revoked', 'reserved',
                        'executing', 'completed', 'failed', 'uncertain'
                    ))
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(approvals)"
                ).fetchall()
            }
            if "executor_pid" not in columns:
                connection.execute(
                    "ALTER TABLE approvals ADD COLUMN executor_pid INTEGER"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS approval_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    approval_id TEXT NOT NULL,
                    execution_id TEXT,
                    event_type TEXT NOT NULL,
                    detail TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )

    @staticmethod
    def _backup_legacy_file(path, source_bytes):
        backup_path = Path(str(path) + ".bak")
        if backup_path.exists():
            if backup_path.read_bytes() == source_bytes:
                return backup_path
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
            backup_path = Path(f"{path}.pre-sqlite-{timestamp}.bak")

        temporary_path = Path(
            f"{backup_path}.tmp-{os.getpid()}-{uuid4().hex}"
        )
        with temporary_path.open("xb") as backup:
            backup.write(source_bytes)
            backup.flush()
            os.fsync(backup.fileno())
        try:
            os.replace(temporary_path, backup_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        return backup_path

    @staticmethod
    def _validate_legacy(data):
        if not isinstance(data, dict):
            raise ValueError("Approval state file must contain an object.")
        normalized = {}
        for approval_id, item in data.items():
            if not isinstance(approval_id, str) or not isinstance(item, dict):
                raise ValueError("Approval state file contains an invalid record.")
            permission_name = item.get("permission_name")
            approved_by = item.get("approved_by")
            if (
                not isinstance(permission_name, str)
                or not isinstance(approved_by, str)
                or not isinstance(item.get("reason", ""), str)
                or (
                    item.get("task_id") is not None
                    and not isinstance(item["task_id"], str)
                )
            ):
                raise ValueError("Approval state file contains an invalid record.")
            expires_at = item.get("expires_at")
            if expires_at is not None:
                if not isinstance(expires_at, str):
                    raise ValueError("Approval expiry must be an ISO timestamp.")
                datetime.fromisoformat(expires_at)
            is_approved = item.get("is_approved", False)
            used = item.get("used", False)
            if not isinstance(is_approved, bool) or not isinstance(used, bool):
                raise ValueError("Approval flags must be boolean values.")
            normalized[approval_id] = {
                "permission_name": permission_name,
                "approved_by": approved_by,
                "reason": item.get("reason", ""),
                "task_id": item.get("task_id"),
                "is_approved": is_approved,
                "used": used,
                "expires_at": expires_at,
            }
        return normalized

    def _import_legacy_if_needed(self):
        if self.legacy_path is None or not self.legacy_path.exists():
            return

        source_bytes = self.legacy_path.read_bytes()
        legacy = self._validate_legacy(json.loads(source_bytes.decode("utf-8")))
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        marker = f"legacy_import:{self.legacy_path.resolve()}"
        backup_path = None

        with self._transaction() as connection:
            already_imported = connection.execute(
                "SELECT value FROM metadata WHERE key = ?", (marker,)
            ).fetchone()
            if already_imported is not None:
                import_metadata = json.loads(already_imported["value"])
            else:
                backup_path = self._backup_legacy_file(
                    self.legacy_path,
                    source_bytes,
                )
                now = datetime.now().astimezone().isoformat()
                for approval_id, item in legacy.items():
                    if item["used"]:
                        status = "uncertain"
                    elif item["is_approved"]:
                        status = "available"
                    else:
                        status = "pending"
                    existing = connection.execute(
                        "SELECT * FROM approvals WHERE approval_id = ?",
                        (approval_id,),
                    ).fetchone()
                    expected_values = (
                        item["permission_name"],
                        item["approved_by"],
                        item["reason"],
                        item["task_id"],
                        int(item["is_approved"]),
                        int(item["used"]),
                        item["expires_at"],
                        status,
                    )
                    if existing is not None:
                        actual_values = tuple(
                            existing[name]
                            for name in (
                                "permission_name",
                                "approved_by",
                                "reason",
                                "task_id",
                                "is_approved",
                                "used",
                                "expires_at",
                                "status",
                            )
                        )
                        if actual_values != expected_values:
                            raise ValueError(
                                "Legacy approval conflicts with existing SQLite data."
                            )
                        continue
                    connection.execute(
                        """
                        INSERT INTO approvals (
                            approval_id, permission_name, approved_by, reason,
                            task_id, is_approved, used, expires_at, status,
                            execution_id, executor_pid, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
                        """,
                        (
                            approval_id,
                            item["permission_name"],
                            item["approved_by"],
                            item["reason"],
                            item["task_id"],
                            int(item["is_approved"]),
                            int(item["used"]),
                            item["expires_at"],
                            status,
                            now,
                        ),
                    )
                import_metadata = {
                    "backup_path": str(backup_path),
                    "imported_count": len(legacy),
                    "imported_at": now,
                    "source_sha256": source_hash,
                }
                connection.execute(
                    "INSERT INTO metadata (key, value) VALUES (?, ?)",
                    (marker, json.dumps(import_metadata)),
                )
                connection.execute(
                    """
                    INSERT INTO approval_events (
                        approval_id, event_type, detail, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        "system",
                        "legacy_import_completed",
                        f"Imported {len(legacy)} records; source backed up.",
                        now,
                    ),
                )

        current_bytes = self.legacy_path.read_bytes()
        if current_bytes == b"{}":
            return
        current_data = self._validate_legacy(
            json.loads(current_bytes.decode("utf-8"))
        )
        current_hash = hashlib.sha256(current_bytes).hexdigest()
        if current_hash != import_metadata.get("source_sha256"):
            if current_data:
                raise ValueError(
                    "Legacy approval file changed after migration; "
                    "it was left untouched for manual review."
                )
            return
        self._write_legacy_tombstone()

    def _write_legacy_tombstone(self):
        temporary_path = Path(
            f"{self.legacy_path}.tmp-{os.getpid()}-{uuid4().hex}"
        )
        try:
            with temporary_path.open("xb") as file:
                file.write(b"{}")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, self.legacy_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _process_is_alive(process_id):
        if not isinstance(process_id, int) or process_id <= 0:
            return False
        if os.name == "nt":
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            open_process = kernel32.OpenProcess
            open_process.argtypes = (
                ctypes.c_ulong,
                ctypes.c_int,
                ctypes.c_ulong,
            )
            open_process.restype = ctypes.c_void_p
            get_exit_code = kernel32.GetExitCodeProcess
            get_exit_code.argtypes = (
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_ulong),
            )
            get_exit_code.restype = ctypes.c_int
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = (ctypes.c_void_p,)
            close_handle.restype = ctypes.c_int
            handle = open_process(0x1000, False, process_id)
            if not handle:
                return ctypes.get_last_error() == 5
            try:
                exit_code = ctypes.c_ulong()
                if not get_exit_code(handle, ctypes.byref(exit_code)):
                    return True
                return exit_code.value == 259
            finally:
                close_handle(handle)
        try:
            os.kill(process_id, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _recover_interrupted_executions(self):
        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT approval_id, execution_id, status, executor_pid
                FROM approvals
                WHERE status IN ('reserved', 'executing')
                """
            ).fetchall()
            now = datetime.now().astimezone().isoformat()
            for row in rows:
                if self._process_is_alive(row["executor_pid"]):
                    continue
                recovered_status = (
                    "failed" if row["status"] == "reserved" else "uncertain"
                )
                event_type = (
                    "reserved_recovered_not_started"
                    if recovered_status == "failed"
                    else "execution_recovered_uncertain"
                )
                detail = (
                    "Process restarted before execution began; action was not invoked."
                    if recovered_status == "failed"
                    else "Process restarted while the external action was executing."
                )
                connection.execute(
                    """
                    UPDATE approvals SET status = ?, executor_pid = NULL,
                        updated_at = ?
                    WHERE approval_id = ? AND status = ?
                    """,
                    (
                        recovered_status, now, row["approval_id"],
                        row["status"],
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO approval_events (
                        approval_id, execution_id, event_type, detail, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        row["approval_id"],
                        row["execution_id"],
                        event_type,
                        detail,
                        now,
                    ),
                )

    @staticmethod
    def _record_values(approval):
        return (
            approval.permission_name,
            approval.approved_by,
            approval.reason,
            approval.task_id,
            int(approval.is_approved),
            int(approval.used),
            approval.expires_at.isoformat() if approval.expires_at else None,
            getattr(approval, "execution_status", "pending"),
            getattr(approval, "execution_id", None),
            datetime.now().astimezone().isoformat(),
            approval.approval_id,
        )

    @staticmethod
    def _as_record(row):
        return dict(row)

    def load_all(self):
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM approvals ORDER BY approval_id"
            ).fetchall()
            return [self._as_record(row) for row in rows]

    def get(self, approval_id):
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            return self._as_record(row) if row is not None else None

    def next_id(self, used_ids=()):
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT approval_id FROM approvals"
            ).fetchall()
        all_ids = set(used_ids)
        all_ids.update(row["approval_id"] for row in rows)
        numbers = [
            int(value[len("approval-"):])
            for value in all_ids
            if value.startswith("approval-")
            and value[len("approval-"):].isdigit()
        ]
        return max(numbers, default=0) + 1

    def create(self, approval_id, approval):
        values = self._record_values(approval)
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO approvals (
                    permission_name, approved_by, reason, task_id,
                    is_approved, used, expires_at, status, execution_id,
                    updated_at, approval_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )

    def save_approval(self, approval):
        values = self._record_values(approval)
        with self._transaction() as connection:
            previous = connection.execute(
                "SELECT used FROM approvals WHERE approval_id = ?",
                (approval.approval_id,),
            ).fetchone()
            if previous is None:
                raise KeyError(
                    f"Approval not found in persistent store: {approval.approval_id}"
                )
            cursor = connection.execute(
                """
                UPDATE approvals SET
                    permission_name = ?, approved_by = ?, reason = ?,
                    task_id = ?, is_approved = ?,
                    used = MAX(used, ?), expires_at = ?,
                    status = CASE
                        WHEN ? = 1 THEN
                            CASE WHEN used = 1 THEN status ELSE 'uncertain' END
                        WHEN ? = 1 THEN 'available'
                        ELSE 'revoked'
                    END,
                    updated_at = ?
                WHERE approval_id = ?
                """,
                (
                    values[0], values[1], values[2], values[3], values[4],
                    values[5], values[6], values[5], values[4],
                    values[9], values[10],
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Approval not found in persistent store: {approval.approval_id}")
            if previous["used"] == 0 and values[5] == 1:
                self._event(
                    connection,
                    approval.approval_id,
                    None,
                    "approval_marked_used",
                    "Approval was marked used outside an execution lifecycle.",
                    values[9],
                )

    @staticmethod
    def _expiry_error(expires_at):
        if expires_at is None:
            return None
        expiry = datetime.fromisoformat(expires_at)
        now = (
            datetime.now(expiry.tzinfo)
            if expiry.tzinfo is not None
            else datetime.now()
        )
        return "Approval expired." if now >= expiry else None

    def claim_use(self, approval, *, permission_name, task_id, execution_id):
        now = datetime.now().astimezone().isoformat()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM approvals WHERE approval_id = ?",
                (approval.approval_id,),
            ).fetchone()
            if row is None:
                return "Approval not found."
            if row["is_approved"] != 1:
                return "Approval not granted."
            if row["permission_name"] != permission_name:
                return "Approval does not match permission."
            if row["task_id"] != task_id:
                return "Approval does not match task."
            expiry_error = self._expiry_error(row["expires_at"])
            if expiry_error is not None:
                return expiry_error
            if row["used"] != 0 or row["status"] != "available":
                return "Approval already used."

            cursor = connection.execute(
                """
                UPDATE approvals
                SET used = 1, status = 'reserved', execution_id = ?,
                    executor_pid = ?, updated_at = ?
                WHERE approval_id = ? AND is_approved = 1 AND used = 0
                    AND status = 'available' AND permission_name = ?
                    AND task_id IS ?
                """,
                (
                    execution_id, os.getpid(), now, approval.approval_id,
                    permission_name, task_id,
                ),
            )
            if cursor.rowcount != 1:
                return "Approval already used."
            self._event(
                connection, approval.approval_id, execution_id,
                "approval_reserved", "Approval reserved before execution.", now,
            )
        approval.used = True
        approval.execution_status = "reserved"
        approval.execution_id = execution_id
        return None

    @staticmethod
    def _event(connection, approval_id, execution_id, event_type, detail, now):
        connection.execute(
            """
            INSERT INTO approval_events (
                approval_id, execution_id, event_type, detail, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (approval_id, execution_id, event_type, detail, now),
        )

    def transition_execution(self, approval, status, *, detail=None):
        if status not in {"executing", "completed", "failed", "uncertain"}:
            raise ValueError(f"Invalid execution status: {status}")
        expected_states = (
            ("reserved",)
            if status == "executing"
            else ("reserved", "executing")
            if status == "failed"
            else ("executing",)
        )
        now = datetime.now().astimezone().isoformat()
        with self._transaction() as connection:
            placeholders = ", ".join("?" for _ in expected_states)
            cursor = connection.execute(
                f"""
                UPDATE approvals SET status = ?, executor_pid = ?,
                    updated_at = ?
                WHERE approval_id = ? AND execution_id = ? AND used = 1
                    AND status IN ({placeholders})
                """,
                (
                    status,
                    os.getpid() if status == "executing" else None,
                    now,
                    approval.approval_id,
                    approval.execution_id, *expected_states,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    f"Approval execution cannot transition to {status}."
                )
            self._event(
                connection,
                approval.approval_id,
                approval.execution_id,
                f"execution_{status}",
                detail,
                now,
            )
        approval.execution_status = status
        return status

    def lifecycle_events(self, approval_id):
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT event_type, execution_id, detail, created_at
                FROM approval_events WHERE approval_id = ?
                ORDER BY event_id
                """,
                (approval_id,),
            ).fetchall()
            return [dict(row) for row in rows]
