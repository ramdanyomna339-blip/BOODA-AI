from threading import Event, Thread

import pytest

from core.approval import BoodaApproval
from core.approval_manager import BoodaApprovalManager
from core.executor import BoodaExecutor
from core.permission_manager import BoodaPermissionManager
from core.permission_policy import BoodaPermissionPolicy
from core.risk import RiskLevel
from core.task import BoodaTask


def test_executor_rejects_missing_permission():
    executor = BoodaExecutor()
    permission_manager = BoodaPermissionManager()
    calls = []

    task = BoodaTask(
        task_id="task-001",
        title="Test task",
    )

    result = executor.execute(
        task=task,
        action=lambda: calls.append("called") or "Executed.",
        permission_manager=permission_manager,
        permission_name="send_message",
    )

    assert result is None
    assert calls == []
    assert task.status == "failed"
    assert task.result == "Permission not found."


def test_executor_rejects_denied_permission():
    executor = BoodaExecutor()
    permission_manager = BoodaPermissionManager()
    calls = []

    permission_manager.add_permission(
        name="send_message",
        category="communication",
        allowed=False,
    )

    task = BoodaTask(
        task_id="task-002",
        title="Denied permission test",
    )

    result = executor.execute(
        task=task,
        action=lambda: calls.append("called") or "Message sent.",
        permission_manager=permission_manager,
        permission_name="send_message",
        permission_policy=BoodaPermissionPolicy(),
    )

    assert result is None
    assert calls == []
    assert task.status == "failed"
    assert task.result == "Permission denied."


def test_executor_allows_granted_permission():
    executor = BoodaExecutor()
    permission_manager = BoodaPermissionManager()

    permission_manager.add_permission(
        name="send_message",
        category="communication",
        allowed=True,
    )

    task = BoodaTask(
        task_id="task-003",
        title="Granted permission test",
    )

    result = executor.execute(
        task=task,
        action=lambda: "Message sent.",
        permission_manager=permission_manager,
        permission_name="send_message",
        permission_policy=BoodaPermissionPolicy(),
    )

    assert result == "Message sent."
    assert task.status == "completed"
    assert task.result == "Message sent."


def test_executor_rejects_high_risk_without_approval():
    executor = BoodaExecutor()
    permission_manager = BoodaPermissionManager()
    permission_policy = BoodaPermissionPolicy()

    permission_manager.add_permission(
        name="spend_money",
        category="finance",
        risk_level=RiskLevel.HIGH,
        allowed=True,
    )
    calls = []

    task = BoodaTask(
        task_id="task-004",
        title="High risk without approval",
    )

    result = executor.execute(
        task=task,
        action=lambda: calls.append("called") or "Money spent.",
        permission_manager=permission_manager,
        permission_name="spend_money",
        permission_policy=permission_policy,
    )

    assert result is None
    assert calls == []
    assert task.status == "failed"
    assert task.result == "Approval required."


def test_executor_rejects_unapproved_high_risk_action():
    executor = BoodaExecutor()
    permission_manager = BoodaPermissionManager()
    permission_policy = BoodaPermissionPolicy()
    approval_manager = BoodaApprovalManager()

    permission_manager.add_permission(
        name="spend_money",
        category="finance",
        risk_level=RiskLevel.HIGH,
        allowed=True,
    )

    approval_id, approval = approval_manager.create_approval(
        permission_name="spend_money",
        approved_by="Yomna",
        reason="Test approval.",
        task_id="task-005",
    )

    task = BoodaTask(
        task_id="task-005",
        title="Unapproved high risk action",
    )
    calls = []

    result = executor.execute(
        task=task,
        action=lambda: calls.append("called") or "Money spent.",
        permission_manager=permission_manager,
        permission_name="spend_money",
        permission_policy=permission_policy,
        approval=approval,
    )

    assert approval_id == "approval-1"
    assert approval.is_approved is False
    assert result is None
    assert calls == []
    assert task.status == "failed"
    assert task.result == "Approval not granted."


def test_executor_allows_approved_high_risk_action():
    executor = BoodaExecutor()
    permission_manager = BoodaPermissionManager()
    permission_policy = BoodaPermissionPolicy()
    approval_manager = BoodaApprovalManager()

    permission_manager.add_permission(
        name="spend_money",
        category="finance",
        risk_level=RiskLevel.HIGH,
        allowed=True,
    )

    approval_id, approval = approval_manager.create_approval(
        permission_name="spend_money",
        approved_by="Yomna",
        reason="Approved test action.",
        task_id="task-006",
    )

    approval.approve()

    task = BoodaTask(
        task_id="task-006",
        title="Approved high risk action",
    )

    result = executor.execute(
        task=task,
        action=lambda: "Money spent.",
        permission_manager=permission_manager,
        permission_name="spend_money",
        permission_policy=permission_policy,
        approval=approval,
    )

    assert approval_id == "approval-1"
    assert approval.is_approved is True
    assert approval.used is True
    assert result == "Money spent."
    assert task.status == "completed"
    assert task.result == "Money spent."


def test_executor_rejects_approval_for_different_task():
    executor = BoodaExecutor()
    permission_manager = BoodaPermissionManager()
    permission_policy = BoodaPermissionPolicy()
    approval_manager = BoodaApprovalManager()

    permission_manager.add_permission(
        name="spend_money",
        category="finance",
        risk_level=RiskLevel.HIGH,
        allowed=True,
    )

    approval_id, approval = approval_manager.create_approval(
        permission_name="spend_money",
        approved_by="Yomna",
        reason="Approval for task-007.",
        task_id="task-007",
    )

    approval.approve()

    task = BoodaTask(
        task_id="task-008",
        title="Different task using old approval",
    )
    calls = []

    result = executor.execute(
        task=task,
        action=lambda: calls.append("called") or "Money spent.",
        permission_manager=permission_manager,
        permission_name="spend_money",
        permission_policy=permission_policy,
        approval=approval,
    )

    assert approval_id == "approval-1"
    assert approval.is_approved is True
    assert approval.used is False
    assert result is None
    assert calls == []
    assert task.status == "failed"
    assert task.result == "Approval does not match task."


def test_executor_rejects_expired_approval():
    executor = BoodaExecutor()
    permission_manager = BoodaPermissionManager()
    permission_policy = BoodaPermissionPolicy()
    approval_manager = BoodaApprovalManager()

    permission_manager.add_permission(
        name="spend_money",
        category="finance",
        risk_level=RiskLevel.HIGH,
        allowed=True,
    )

    approval_id, approval = approval_manager.create_approval(
        permission_name="spend_money",
        approved_by="Yomna",
        reason="Expired approval test.",
        task_id="task-009",
        expires_in_minutes=-1,
    )

    approval.approve()

    task = BoodaTask(
        task_id="task-009",
        title="Expired approval test",
    )
    calls = []

    result = executor.execute(
        task=task,
        action=lambda: calls.append("called") or "Money spent.",
        permission_manager=permission_manager,
        permission_name="spend_money",
        permission_policy=permission_policy,
        approval=approval,
    )

    assert approval_id == "approval-1"
    assert approval.is_approved is True
    assert approval.is_expired() is True
    assert approval.used is False
    assert result is None
    assert calls == []
    assert task.status == "failed"
    assert task.result == "Approval expired."


def test_executor_rejects_missing_permission_manager_without_calling_action():
    calls = []
    task = BoodaTask("task-010", "Missing permission manager")

    result = BoodaExecutor().execute(
        task=task,
        action=lambda: calls.append("called"),
        permission_name="send_message",
        permission_policy=BoodaPermissionPolicy(),
    )

    assert result is None
    assert calls == []
    assert task.status == "failed"
    assert task.result == "Permission manager is required."


@pytest.mark.parametrize("permission_name", [None, "", "   ", " send_message "])
def test_executor_rejects_missing_or_invalid_permission_name(
    permission_name,
):
    calls = []
    permissions = BoodaPermissionManager()
    permissions.add_permission("send_message", allowed=True)
    task = BoodaTask("task-011", "Invalid permission name")

    result = BoodaExecutor().execute(
        task=task,
        action=lambda: calls.append("called"),
        permission_manager=permissions,
        permission_name=permission_name,
        permission_policy=BoodaPermissionPolicy(),
    )

    assert result is None
    assert calls == []
    assert task.status == "failed"
    assert task.result == "A valid permission name is required."


@pytest.mark.parametrize("risk_level", [RiskLevel.HIGH, RiskLevel.CRITICAL])
def test_executor_rejects_high_risk_action_without_policy(risk_level):
    calls = []
    permissions = BoodaPermissionManager()
    permissions.add_permission(
        "spend_money",
        risk_level=risk_level,
        allowed=True,
    )
    task = BoodaTask("task-012", "Missing permission policy")

    result = BoodaExecutor().execute(
        task=task,
        action=lambda: calls.append("called"),
        permission_manager=permissions,
        permission_name="spend_money",
        approval=object(),
    )

    assert result is None
    assert calls == []
    assert task.status == "failed"
    assert task.result == "Permission policy is required."


def test_executor_allows_high_risk_only_with_approval_even_if_policy_returns_false():
    class WeakeningPolicy:
        def requires_approval(self, _permission):
            return False

        def requires_task_bound_approval(self, _permission):
            return False

    permissions = BoodaPermissionManager()
    permissions.add_permission(
        "spend_money",
        risk_level=RiskLevel.HIGH,
        allowed=True,
    )
    approval_manager = BoodaApprovalManager()
    approval_id, approval = approval_manager.create_approval(
        permission_name="spend_money",
        approved_by="owner",
        task_id="task-024",
    )
    approval_manager.approve_approval(approval_id)
    calls = []
    task = BoodaTask("task-024", "High-risk action with policy override")

    result = BoodaExecutor().execute(
        task=task,
        action=lambda: calls.append("called") or "completed",
        permission_manager=permissions,
        permission_name="spend_money",
        permission_policy=WeakeningPolicy(),
        approval=approval,
    )

    assert result == "completed"
    assert calls == ["called"]
    assert task.status == "completed"
    assert approval.used is True


def test_executor_rejects_permission_when_allowed_state_is_not_explicit_true():
    class AmbiguousPermission:
        name = "send_message"
        allowed = "yes"

    class PermissionManager:
        def get_permission(self, _name):
            return AmbiguousPermission()

    calls = []
    task = BoodaTask("task-013", "Ambiguous permission")

    result = BoodaExecutor().execute(
        task=task,
        action=lambda: calls.append("called"),
        permission_manager=PermissionManager(),
        permission_name="send_message",
        permission_policy=BoodaPermissionPolicy(),
    )

    assert result is None
    assert calls == []
    assert task.status == "failed"
    assert task.result == "Permission denied."


def test_executor_rejects_permission_lookup_exception_without_calling_action():
    class PermissionManager:
        def get_permission(self, _name):
            raise RuntimeError("Permission store unavailable.")

    calls = []
    task = BoodaTask("task-014", "Permission lookup failure")
    audit_events = []

    class AuditLog:
        def record(self, **event):
            audit_events.append(event)

    with pytest.raises(RuntimeError, match="Permission store unavailable"):
        BoodaExecutor().execute(
            task=task,
            action=lambda: calls.append("called"),
            permission_manager=PermissionManager(),
            permission_name="send_message",
            permission_policy=BoodaPermissionPolicy(),
            audit_log=AuditLog(),
        )

    assert calls == []
    assert task.status == "failed"
    assert task.result == "Permission or approval validation failed."
    assert len(audit_events) == 1
    assert audit_events[0]["outcome"] == "rejected"


def test_executor_rejects_policy_exception_without_calling_action():
    class FailingPolicy:
        def requires_approval(self, _permission):
            raise RuntimeError("Policy unavailable.")

    calls = []
    permissions = BoodaPermissionManager()
    permissions.add_permission("send_message", allowed=True)
    task = BoodaTask("task-015", "Permission policy failure")
    audit_events = []

    class AuditLog:
        def record(self, **event):
            audit_events.append(event)

    with pytest.raises(RuntimeError, match="Policy unavailable"):
        BoodaExecutor().execute(
            task=task,
            action=lambda: calls.append("called"),
            permission_manager=permissions,
            permission_name="send_message",
            permission_policy=FailingPolicy(),
            audit_log=AuditLog(),
        )

    assert calls == []
    assert task.status == "failed"
    assert task.result == "Permission or approval validation failed."
    assert len(audit_events) == 1
    assert audit_events[0]["outcome"] == "rejected"


def test_executor_rejects_invalid_policy_decision_without_calling_action():
    class InvalidPolicy:
        def requires_approval(self, _permission):
            return None

    calls = []
    permissions = BoodaPermissionManager()
    permissions.add_permission("send_message", allowed=True)
    task = BoodaTask("task-016", "Invalid policy decision")

    result = BoodaExecutor().execute(
        task=task,
        action=lambda: calls.append("called"),
        permission_manager=permissions,
        permission_name="send_message",
        permission_policy=InvalidPolicy(),
    )

    assert result is None
    assert calls == []
    assert task.status == "failed"
    assert task.result == "Permission policy returned an invalid approval decision."


@pytest.mark.parametrize("risk_level", [RiskLevel.HIGH, RiskLevel.CRITICAL])
def test_executor_requires_approval_for_high_risk_when_policy_returns_false(
    risk_level,
):
    class WeakeningPolicy:
        def requires_approval(self, _permission):
            return False

        def requires_task_bound_approval(self, _permission):
            return False

    calls = []
    permissions = BoodaPermissionManager()
    permissions.add_permission(
        "spend_money",
        risk_level=risk_level,
        allowed=True,
    )
    task = BoodaTask("task-017", "Policy cannot weaken high-risk approval")

    result = BoodaExecutor().execute(
        task=task,
        action=lambda: calls.append("called"),
        permission_manager=permissions,
        permission_name="spend_money",
        permission_policy=WeakeningPolicy(),
    )

    assert result is None
    assert calls == []
    assert task.status == "failed"
    assert task.result == "Approval required."


def test_executor_rejects_permission_object_with_different_name():
    class PermissionManager:
        def get_permission(self, _name):
            from core.permission import BoodaPermission

            return BoodaPermission("different_permission", allowed=True)

    calls = []
    task = BoodaTask("task-018", "Mismatched permission object")

    result = BoodaExecutor().execute(
        task=task,
        action=lambda: calls.append("called"),
        permission_manager=PermissionManager(),
        permission_name="send_message",
        permission_policy=BoodaPermissionPolicy(),
    )

    assert result is None
    assert calls == []
    assert task.status == "failed"
    assert task.result == "Permission does not match the requested permission."


def test_executor_rejects_unknown_permission_risk_level():
    class PermissionManager:
        def get_permission(self, _name):
            from core.permission import BoodaPermission

            return BoodaPermission(
                "send_message",
                risk_level="unrecognized",
                allowed=True,
            )

    calls = []
    task = BoodaTask("task-019", "Unknown permission risk")

    result = BoodaExecutor().execute(
        task=task,
        action=lambda: calls.append("called"),
        permission_manager=PermissionManager(),
        permission_name="send_message",
        permission_policy=BoodaPermissionPolicy(),
    )

    assert result is None
    assert calls == []
    assert task.status == "failed"
    assert task.result == "Permission has an unknown risk level."


def test_executor_reserves_approval_before_action_and_blocks_concurrent_reuse(
    tmp_path,
):
    permissions = BoodaPermissionManager()
    permissions.add_permission(
        "spend_money",
        risk_level=RiskLevel.HIGH,
        allowed=True,
    )
    policy = BoodaPermissionPolicy()
    approvals = BoodaApprovalManager(
        file_path=tmp_path / "approvals.json"
    )
    approval_file_path = tmp_path / "approvals.json"
    approval_id, approval = approvals.create_approval(
        permission_name="spend_money",
        approved_by="owner",
        task_id="task-020",
    )
    approvals.approve_approval(approval_id)
    action_started = Event()
    release_action = Event()
    first_calls = []

    def first_action():
        first_calls.append("first")
        persisted_approval = BoodaApprovalManager(
            file_path=approval_file_path
        ).get_approval(approval_id)
        assert persisted_approval.used is True
        action_started.set()
        assert release_action.wait(timeout=5)
        return "completed"

    first_result = []

    def execute_first():
        first_result.append(BoodaExecutor().execute(
            task=BoodaTask("task-020", "First concurrent execution"),
            action=first_action,
            permission_manager=permissions,
            permission_name="spend_money",
            permission_policy=policy,
            approval=approval,
        ))

    first_thread = Thread(target=execute_first)
    first_thread.start()
    assert action_started.wait(timeout=5)

    second_calls = []
    second_task = BoodaTask("task-020", "Second concurrent execution")
    second_result = BoodaExecutor().execute(
        task=second_task,
        action=lambda: second_calls.append("second"),
        permission_manager=permissions,
        permission_name="spend_money",
        permission_policy=policy,
        approval=approval,
    )
    release_action.set()
    first_thread.join(timeout=5)

    assert not first_thread.is_alive()
    assert first_result == ["completed"]
    assert first_calls == ["first"]
    assert second_result is None
    assert second_calls == []
    assert second_task.status == "failed"
    assert second_task.result == "Approval already used."
    assert approval.used is True
    assert approvals.get_approval(approval_id).used is True
    assert BoodaApprovalManager(
        file_path=approval_file_path
    ).get_approval(approval_id).used is True


def test_executor_does_not_run_action_when_approval_persistence_fails(tmp_path):
    permissions = BoodaPermissionManager()
    permissions.add_permission(
        "spend_money",
        risk_level=RiskLevel.HIGH,
        allowed=True,
    )
    approval = BoodaApproval(
        permission_name="spend_money",
        approved_by="owner",
        task_id="task-021",
        is_approved=True,
    )

    def fail_to_persist():
        raise OSError("Approval storage unavailable.")

    approval._on_change = fail_to_persist
    calls = []
    task = BoodaTask("task-021", "Approval persistence failure")
    audit_events = []

    class AuditLog:
        def record(self, **event):
            audit_events.append(event)

    with pytest.raises(OSError, match="Approval storage unavailable"):
        BoodaExecutor().execute(
            task=task,
            action=lambda: calls.append("called"),
            permission_manager=permissions,
            permission_name="spend_money",
            permission_policy=BoodaPermissionPolicy(),
            approval=approval,
            audit_log=AuditLog(),
        )

    assert calls == []
    assert approval.used is True
    assert task.status == "failed"
    assert task.result == "Approval reservation failed."
    assert len(audit_events) == 1
    assert audit_events[0]["outcome"] == "rejected"


def test_executor_does_not_run_action_when_sqlite_reservation_fails(tmp_path):
    permissions = BoodaPermissionManager()
    permissions.add_permission(
        "spend_money",
        risk_level=RiskLevel.HIGH,
        allowed=True,
    )
    approvals = BoodaApprovalManager(file_path=tmp_path / "approvals.json")
    approval_id, approval = approvals.create_approval(
        permission_name="spend_money",
        approved_by="owner",
        task_id="task-sqlite-reserve-failure",
    )
    approvals.approve_approval(approval_id)

    def fail_reservation(*_args, **_kwargs):
        raise OSError("SQLite reservation unavailable.")

    approval._store.claim_use = fail_reservation
    calls = []
    task = BoodaTask("task-sqlite-reserve-failure", "Storage failure")

    with pytest.raises(OSError, match="SQLite reservation unavailable"):
        BoodaExecutor().execute(
            task=task,
            action=lambda: calls.append("called"),
            permission_manager=permissions,
            permission_name="spend_money",
            permission_policy=BoodaPermissionPolicy(),
            approval=approval,
        )

    assert calls == []
    assert task.status == "failed"
    assert task.result == "Approval reservation failed."


def test_action_exception_leaves_approval_uncertain_and_not_reusable(tmp_path):
    file_path = tmp_path / "approvals.json"
    approvals = BoodaApprovalManager(file_path=file_path)
    approval_id, approval = approvals.create_approval(
        permission_name="spend_money",
        approved_by="owner",
        task_id="task-uncertain",
    )
    approvals.approve_approval(approval_id)
    permissions = BoodaPermissionManager()
    permissions.add_permission(
        "spend_money",
        risk_level=RiskLevel.HIGH,
        allowed=True,
    )
    calls = []

    def action_with_uncertain_effect():
        calls.append("started")
        raise OSError("External system response was lost.")

    task = BoodaTask("task-uncertain", "Uncertain action")
    result = BoodaExecutor().execute(
        task=task,
        action=action_with_uncertain_effect,
        permission_manager=permissions,
        permission_name="spend_money",
        permission_policy=BoodaPermissionPolicy(),
        approval=approval,
    )

    assert result is None
    assert calls == ["started"]
    assert task.status == "uncertain"
    assert "outcome is uncertain" in task.result
    assert approval.execution_status == "uncertain"

    reopened = BoodaApprovalManager(file_path=file_path)
    restored = reopened.get_approval(approval_id)
    assert restored.used is True
    assert restored.execution_status == "uncertain"
    assert reopened._store.lifecycle_events(approval_id)[-1]["event_type"] == (
        "execution_uncertain"
    )

    retry_calls = []
    retry_result = BoodaExecutor().execute(
        task=BoodaTask("task-uncertain", "Retry attempt"),
        action=lambda: retry_calls.append("called"),
        permission_manager=permissions,
        permission_name="spend_money",
        permission_policy=BoodaPermissionPolicy(),
        approval=restored,
    )
    assert retry_result is None
    assert retry_calls == []


def test_action_exception_without_approval_is_not_reported_as_confirmed_failure(
    tmp_path,
):
    from core.audit_log import BoodaAuditLog
    from core.task_manager import BoodaTaskManager

    audit_log = BoodaAuditLog(tmp_path / "audit.jsonl")
    permissions = BoodaPermissionManager()
    permissions.add_permission("send_message", allowed=True)
    task_manager = BoodaTaskManager(tmp_path / "tasks.json")
    task = task_manager.add_task(
        "task-uncertain-no-approval",
        "Uncertain external action",
    )
    calls = []

    def action_that_may_have_external_effect():
        calls.append("started")
        raise OSError("Remote response lost.")

    result = BoodaExecutor().execute(
        task=task,
        action=action_that_may_have_external_effect,
        permission_manager=permissions,
        permission_name="send_message",
        permission_policy=BoodaPermissionPolicy(),
        audit_log=audit_log,
    )

    events = audit_log.get_events()
    assert result is None
    assert calls == ["started"]
    assert task.status == "uncertain"
    assert "external effect may have occurred" in task.result
    assert events[-1].outcome == "uncertain"
    assert "may have occurred" in events[-1].rejection_reason
    restored_task = BoodaTaskManager(
        tmp_path / "tasks.json"
    ).get_task(task.task_id)
    assert restored_task.status == "uncertain"


def test_execution_start_audit_failure_prevents_action_and_consumes_approval(
    tmp_path,
):
    class FailingAuditLog:
        def record(self, **event):
            if event["action"] == "execution_started":
                raise OSError("Audit storage unavailable.")

    file_path = tmp_path / "approvals.json"
    approvals = BoodaApprovalManager(file_path=file_path)
    approval_id, approval = approvals.create_approval(
        permission_name="spend_money",
        approved_by="owner",
        task_id="task-start-audit",
    )
    approvals.approve_approval(approval_id)
    permissions = BoodaPermissionManager()
    permissions.add_permission(
        "spend_money",
        risk_level=RiskLevel.HIGH,
        allowed=True,
    )
    calls = []
    task = BoodaTask("task-start-audit", "Audit start failure")

    with pytest.raises(OSError, match="Audit storage unavailable"):
        BoodaExecutor().execute(
            task=task,
            action=lambda: calls.append("called"),
            permission_manager=permissions,
            permission_name="spend_money",
            permission_policy=BoodaPermissionPolicy(),
            approval=approval,
            audit_log=FailingAuditLog(),
        )

    assert calls == []
    assert task.status == "failed"
    assert task.result == "Execution could not be audited; the action was not invoked."
    assert approval.used is True
    assert approval.execution_status == "failed"
    reopened = BoodaApprovalManager(file_path=file_path)
    assert reopened.get_approval(approval_id).execution_status == "failed"


def test_final_approval_persistence_failure_does_not_hide_action_success(
    tmp_path,
):
    permissions = BoodaPermissionManager()
    permissions.add_permission(
        "spend_money",
        risk_level=RiskLevel.HIGH,
        allowed=True,
    )
    approvals = BoodaApprovalManager(
        file_path=tmp_path / "approvals.json"
    )
    approval_id, approval = approvals.create_approval(
        permission_name="spend_money",
        approved_by="owner",
        task_id="task-result-persistence",
    )
    approvals.approve_approval(approval_id)
    original_finish = approval.finish_execution

    def fail_completed_state(status, *, detail=None):
        if status == "completed":
            raise OSError("Approval result storage unavailable.")
        return original_finish(status, detail=detail)

    approval.finish_execution = fail_completed_state
    calls = []
    task = BoodaTask("task-result-persistence", "Result persistence failure")

    with pytest.raises(RuntimeError, match="Action returned successfully"):
        BoodaExecutor().execute(
            task=task,
            action=lambda: calls.append("called") or "completed result",
            permission_manager=permissions,
            permission_name="spend_money",
            permission_policy=BoodaPermissionPolicy(),
            approval=approval,
        )

    assert calls == ["called"]
    assert task.status == "completed"
    assert task.result == "completed result"
    assert approval.used is True
    assert approval.execution_status == "executing"


def test_task_start_failure_prevents_action_and_marks_approval_failed(tmp_path):
    class FailingStartTask(BoodaTask):
        def start(self):
            self.status = "running"
            raise OSError("Task storage unavailable.")

    file_path = tmp_path / "approvals.json"
    approvals = BoodaApprovalManager(file_path=file_path)
    approval_id, approval = approvals.create_approval(
        permission_name="spend_money",
        approved_by="owner",
        task_id="task-start-failure",
    )
    approvals.approve_approval(approval_id)
    permissions = BoodaPermissionManager()
    permissions.add_permission(
        "spend_money",
        risk_level=RiskLevel.HIGH,
        allowed=True,
    )
    calls = []
    task = FailingStartTask("task-start-failure", "Task start failure")

    with pytest.raises(OSError, match="Task storage unavailable"):
        BoodaExecutor().execute(
            task=task,
            action=lambda: calls.append("called"),
            permission_manager=permissions,
            permission_name="spend_money",
            permission_policy=BoodaPermissionPolicy(),
            approval=approval,
        )

    assert calls == []
    assert task.status == "failed"
    assert approval.execution_status == "failed"
    assert approvals.get_approval(approval_id).used is True


def test_executor_rejects_without_action_when_task_failure_update_raises():
    class FailingTask(BoodaTask):
        def fail(self, result=None):
            raise OSError("Task state storage unavailable.")

    class AuditLog:
        def __init__(self):
            self.events = []

        def record(self, **event):
            self.events.append(event)

    calls = []
    audit_log = AuditLog()
    task = FailingTask("task-022", "Task state failure")

    with pytest.raises(OSError, match="Task state storage unavailable"):
        BoodaExecutor().execute(
            task=task,
            action=lambda: calls.append("called"),
            audit_log=audit_log,
        )

    assert calls == []
    assert len(audit_log.events) == 1
    assert audit_log.events[0]["outcome"] == "rejected"


def test_executor_rejects_without_action_when_rejection_audit_fails():
    class FailingAuditLog:
        def record(self, **_event):
            raise OSError("Audit storage unavailable.")

    calls = []
    task = BoodaTask("task-023", "Audit storage failure")

    with pytest.raises(OSError, match="Audit storage unavailable"):
        BoodaExecutor().execute(
            task=task,
            action=lambda: calls.append("called"),
            audit_log=FailingAuditLog(),
        )

    assert calls == []
    assert task.status == "failed"
    assert task.result == "Permission manager is required."


def test_executor_preserves_completed_task_when_completion_audit_fails():
    class FailingAuditLog:
        def record(self, **event):
            if event["outcome"] == "completed":
                raise OSError("Audit storage unavailable.")

    permissions = BoodaPermissionManager()
    permissions.add_permission("save_file", allowed=True)
    calls = []
    task = BoodaTask("task-025", "Completion audit failure")

    with pytest.raises(OSError, match="Audit storage unavailable"):
        BoodaExecutor().execute(
            task=task,
            action=lambda: calls.append("called") or "saved",
            permission_manager=permissions,
            permission_name="save_file",
            permission_policy=BoodaPermissionPolicy(),
            audit_log=FailingAuditLog(),
        )

    assert calls == ["called"]
    assert task.status == "completed"
    assert task.result == "saved"