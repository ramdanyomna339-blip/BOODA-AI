from types import SimpleNamespace

from core.approval_manager import BoodaApprovalManager


class FakeAuditLog:
    def __init__(self, events=None):
        self.events = list(events or [])

    def get_events(self):
        return self.events

    def record(self, **event_data):
        self.events.append(SimpleNamespace(**event_data))


def test_new_approval_id_does_not_repeat_audit_history(tmp_path):
    audit_log = FakeAuditLog(
        events=[
            SimpleNamespace(approval_id="approval-1"),
        ]
    )
    file_path = tmp_path / "approvals.json"

    first_manager = BoodaApprovalManager(
        audit_log=audit_log,
        file_path=file_path,
    )
    first_id, _ = first_manager.create_approval(
        permission_name="spend_money",
        approved_by="Yomna",
    )

    reopened_manager = BoodaApprovalManager(
        audit_log=audit_log,
        file_path=file_path,
    )
    second_id, _ = reopened_manager.create_approval(
        permission_name="send_message",
        approved_by="Yomna",
    )

    assert first_id == "approval-2"
    assert second_id == "approval-3"