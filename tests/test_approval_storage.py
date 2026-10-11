import json
import multiprocessing
import os
import sqlite3

import pytest

from core.approval_manager import BoodaApprovalManager


def _claim_approval_in_process(file_path, approval_id, result_queue):
    manager = BoodaApprovalManager(file_path=file_path)
    approval = manager.get_approval(approval_id)
    result_queue.put(
        approval.claim_use(
            permission_name="spend_money",
            task_id="task-process-claim",
        )
    )


def _start_execution_and_exit(file_path, approval_id, result_queue):
    manager = BoodaApprovalManager(file_path=file_path)
    approval = manager.get_approval(approval_id)
    claim_result = approval.claim_use(
        permission_name="spend_money",
        task_id="task-process-recovery",
    )
    if claim_result is not None:
        result_queue.put(claim_result)
        return
    approval.start_execution()
    result_queue.put("executing")


def test_approval_state_survives_reopening(tmp_path):
    file_path = tmp_path / "security" / "approvals.json"

    first_manager = BoodaApprovalManager(file_path=file_path)
    approval_id, approval = first_manager.create_approval(
        permission_name="spend_money",
        approved_by="Yomna",
        reason="Approved purchase.",
        task_id="task-approval-001",
        expires_in_minutes=30,
    )
    original_expiry = approval.expires_at

    assert first_manager.approve_approval(approval_id)
    approval.mark_used()

    second_manager = BoodaApprovalManager(file_path=file_path)
    restored_approval = second_manager.get_approval(approval_id)

    assert restored_approval is not None
    assert restored_approval.permission_name == "spend_money"
    assert restored_approval.task_id == "task-approval-001"
    assert restored_approval.reason == "Approved purchase."
    assert restored_approval.is_approved is True
    assert restored_approval.used is True
    assert restored_approval.expires_at == original_expiry

    assert second_manager.revoke_approval(
        approval_id,
        revoked_by="Yomna",
    )

    third_manager = BoodaApprovalManager(file_path=file_path)
    restored_approval = third_manager.get_approval(approval_id)

    assert restored_approval.is_approved is False
    assert restored_approval.used is True


def test_legacy_json_is_backed_up_and_tombstoned_during_migration(tmp_path):
    file_path = tmp_path / "approvals.json"
    legacy_data = {
        "approval-7": {
            "permission_name": "spend_money",
            "approved_by": "owner",
            "reason": "test",
            "task_id": "task-legacy",
            "is_approved": True,
            "used": False,
            "expires_at": None,
        }
    }
    original_bytes = json.dumps(legacy_data, ensure_ascii=False).encode("utf-8")
    file_path.write_bytes(original_bytes)

    manager = BoodaApprovalManager(file_path=file_path)

    assert manager.get_approval("approval-7").is_approved is True
    assert manager.get_approval("approval-7").used is False
    assert file_path.read_bytes() == b"{}"
    assert (tmp_path / "approvals.json.bak").read_bytes() == original_bytes
    assert (tmp_path / "approvals.json.sqlite3").exists()

    reopened = BoodaApprovalManager(file_path=file_path)
    with sqlite3.connect(str(file_path) + ".sqlite3") as connection:
        approval_count = connection.execute(
            "SELECT COUNT(*) FROM approvals WHERE approval_id = 'approval-7'"
        ).fetchone()[0]
        import_event_count = connection.execute(
            "SELECT COUNT(*) FROM approval_events WHERE event_type = 'legacy_import_completed'"
        ).fetchone()[0]
    assert reopened.get_approval("approval-7").is_approved is True
    assert approval_count == 1
    assert import_event_count == 1


def test_consumed_migrated_approval_cannot_be_restored_from_legacy_json(
    tmp_path,
):
    file_path = tmp_path / "approvals.json"
    legacy_data = {
        "approval-2": {
            "permission_name": "spend_money",
            "approved_by": "owner",
            "reason": "migration reuse check",
            "task_id": "task-legacy-consume",
            "is_approved": True,
            "used": False,
            "expires_at": None,
        }
    }
    source_bytes = json.dumps(legacy_data).encode("utf-8")
    file_path.write_bytes(source_bytes)

    manager = BoodaApprovalManager(file_path=file_path)
    approval = manager.get_approval("approval-2")
    assert approval.claim_use(
        permission_name="spend_money",
        task_id="task-legacy-consume",
    ) is None

    assert file_path.read_bytes() == b"{}"
    assert (tmp_path / "approvals.json.bak").read_bytes() == source_bytes
    reopened = BoodaApprovalManager(file_path=file_path)
    restored = reopened.get_approval("approval-2")
    assert restored.used is True
    assert restored.execution_status == "reserved"
    assert restored.claim_use(
        permission_name="spend_money",
        task_id="task-legacy-consume",
    ) == "Approval already used."


def test_corrupt_legacy_json_stops_without_modifying_source(tmp_path):
    file_path = tmp_path / "approvals.json"
    corrupt_bytes = b'{"approval-1":'
    file_path.write_bytes(corrupt_bytes)

    with pytest.raises(json.JSONDecodeError):
        BoodaApprovalManager(file_path=file_path)

    assert file_path.read_bytes() == corrupt_bytes
    assert not (tmp_path / "approvals.json.bak").exists()


def test_two_independent_processes_cannot_claim_same_approval(tmp_path):
    file_path = tmp_path / "approvals.json"
    manager = BoodaApprovalManager(file_path=file_path)
    approval_id, _ = manager.create_approval(
        permission_name="spend_money",
        approved_by="owner",
        task_id="task-process-claim",
    )
    assert manager.approve_approval(approval_id)

    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_claim_approval_in_process,
            args=(str(file_path), approval_id, result_queue),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()

    results = [result_queue.get(timeout=15) for _ in processes]
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    assert results.count(None) == 1
    assert results.count("Approval already used.") == 1
    reopened = BoodaApprovalManager(file_path=file_path)
    approval = reopened.get_approval(approval_id)
    assert approval.used is True
    assert approval.execution_status == "failed"
    assert reopened._store.lifecycle_events(approval_id)[-1]["event_type"] == (
        "reserved_recovered_not_started"
    )


def test_restart_marks_interrupted_execution_uncertain_and_never_releases_it(
    tmp_path,
):
    file_path = tmp_path / "approvals.json"
    manager = BoodaApprovalManager(file_path=file_path)
    approval_id, approval = manager.create_approval(
        permission_name="spend_money",
        approved_by="owner",
        task_id="task-restart",
    )
    assert manager.approve_approval(approval_id)
    assert approval.claim_use(
        permission_name="spend_money",
        task_id="task-restart",
    ) is None
    approval.start_execution()
    database_path = str(file_path) + ".sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE approvals SET executor_pid = ? WHERE approval_id = ?",
            (2_147_483_647, approval_id),
        )

    reopened = BoodaApprovalManager(file_path=file_path)
    restored = reopened.get_approval(approval_id)

    assert restored.used is True
    assert restored.execution_status == "uncertain"
    assert reopened._store.lifecycle_events(approval_id)[-1]["event_type"] == (
        "execution_recovered_uncertain"
    )


def test_live_process_is_not_recovered_as_stopped(tmp_path):
    file_path = tmp_path / "approvals.json"
    manager = BoodaApprovalManager(file_path=file_path)
    approval_id, approval = manager.create_approval(
        permission_name="spend_money",
        approved_by="owner",
        task_id="task-live-process",
    )
    manager.approve_approval(approval_id)
    assert approval.claim_use(
        permission_name="spend_money",
        task_id="task-live-process",
    ) is None
    approval.start_execution()

    database_path = str(file_path) + ".sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE approvals SET executor_pid = ? WHERE approval_id = ?",
            (os.getpid(), approval_id),
        )

    reopened = BoodaApprovalManager(file_path=file_path)

    assert reopened.get_approval(approval_id).execution_status == "executing"
    assert reopened._store.lifecycle_events(approval_id)[-1]["event_type"] == (
        "execution_executing"
    )


def test_terminated_process_execution_recovers_as_uncertain(tmp_path):
    file_path = tmp_path / "approvals.json"
    manager = BoodaApprovalManager(file_path=file_path)
    approval_id, _ = manager.create_approval(
        permission_name="spend_money",
        approved_by="owner",
        task_id="task-process-recovery",
    )
    manager.approve_approval(approval_id)

    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    process = context.Process(
        target=_start_execution_and_exit,
        args=(str(file_path), approval_id, result_queue),
    )
    process.start()
    assert result_queue.get(timeout=15) == "executing"
    process.join(timeout=15)
    assert process.exitcode == 0

    reopened = BoodaApprovalManager(file_path=file_path)
    recovered = reopened.get_approval(approval_id)
    assert recovered.used is True
    assert recovered.execution_status == "uncertain"
    assert reopened._store.lifecycle_events(approval_id)[-1]["event_type"] == (
        "execution_recovered_uncertain"
    )


def test_successful_execution_state_survives_manager_reopen(tmp_path):
    file_path = tmp_path / "approvals.json"
    manager = BoodaApprovalManager(file_path=file_path)
    approval_id, approval = manager.create_approval(
        permission_name="spend_money",
        approved_by="owner",
        task_id="task-complete",
    )
    manager.approve_approval(approval_id)
    assert approval.claim_use(
        permission_name="spend_money",
        task_id="task-complete",
    ) is None
    approval.start_execution()
    approval.finish_execution("completed", detail="Action returned successfully.")

    reopened = BoodaApprovalManager(file_path=file_path)
    restored = reopened.get_approval(approval_id)

    assert restored.used is True
    assert restored.execution_status == "completed"
    assert reopened._store.lifecycle_events(approval_id)[-1]["event_type"] == (
        "execution_completed"
    )


def test_legacy_migration_conflict_preserves_source_and_backup(tmp_path):
    file_path = tmp_path / "approvals.json"
    legacy_data = {
        "approval-1": {
            "permission_name": "spend_money",
            "approved_by": "owner",
            "reason": "legacy",
            "task_id": "task-conflict",
            "is_approved": True,
            "used": False,
            "expires_at": None,
        }
    }
    source_bytes = json.dumps(legacy_data).encode("utf-8")
    file_path.write_bytes(source_bytes)
    database_path = str(file_path) + ".sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE approvals (
                approval_id TEXT PRIMARY KEY,
                permission_name TEXT NOT NULL,
                approved_by TEXT NOT NULL,
                reason TEXT NOT NULL,
                task_id TEXT,
                is_approved INTEGER NOT NULL,
                used INTEGER NOT NULL,
                expires_at TEXT,
                status TEXT NOT NULL,
                execution_id TEXT,
                executor_pid INTEGER,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO approvals VALUES (
                'approval-1', 'send_message', 'owner', 'conflict',
                'task-conflict', 1, 0, NULL, 'available', NULL, NULL, 'now'
            )
            """
        )

    with pytest.raises(ValueError, match="conflicts with existing SQLite data"):
        BoodaApprovalManager(file_path=file_path)

    assert file_path.read_bytes() == source_bytes
    assert (tmp_path / "approvals.json.bak").read_bytes() == source_bytes