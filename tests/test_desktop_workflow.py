from types import SimpleNamespace
import pytest
from core.desktop_workflow import notepad_check


def request(flow, status="completed"):
    step = flow.next_step()
    task = SimpleNamespace(task_id=str(flow.index), status=status,
        metadata={"operation": step["operation"], "parameters": step["parameters"]})
    flow.bind(task)
    return task


def test_next_action_waits_for_execution_and_human_result_check():
    flow = notepad_check()
    task = request(flow)
    with pytest.raises(ValueError):
        flow.next_step()
    flow.record(task)
    with pytest.raises(ValueError):
        flow.next_step()
    flow.verify(True)
    assert flow.next_step()["operation"] == "type"
    task = request(flow)
    flow.record(task)
    flow.verify(True)
    assert flow.state == "completed"
    assert all(item["verified_by_user"] for item in flow.history)


@pytest.mark.parametrize("status", ["uncertain", "blocked", "failed"])
def test_failed_or_uncertain_input_cannot_continue_or_retry_automatically(status):
    flow = notepad_check()
    flow.record(request(flow, status))
    assert flow.state == "stopped"
    with pytest.raises(ValueError):
        flow.next_step()


def test_rejected_result_stops_remaining_steps():
    flow = notepad_check()
    flow.record(request(flow))
    flow.verify(False)
    assert flow.state == "stopped"
    assert not flow.history[-1]["verified_by_user"]


def test_mismatched_step_cannot_be_bound():
    flow = notepad_check()
    with pytest.raises(ValueError):
        flow.bind(SimpleNamespace(task_id="wrong", metadata={"operation": "type", "parameters": {"text": "other"}}))


@pytest.mark.parametrize("second_approval", ["موافق", "لا"])
def test_menu_requires_separate_approval_for_each_step(tmp_path, monkeypatch, second_approval):
    from core.system_cli import manage_desktop
    from core.permission_manager import BoodaPermissionManager
    from core.approval_manager import BoodaApprovalManager
    from core.desktop_control import DESKTOP_PERMISSION
    calls = []
    class Backend:
        selected_window = None
        def target(self): return {"window": 1, "title": "empty test notepad"}
        def windows(self): return [self.target()]
        def validate(self, *args): pass
        def perform(self, operation, parameters):
            calls.append(operation)
            return {"input_sent": True}
    monkeypatch.setattr("core.desktop_control.WindowsDesktopBackend", lambda **kwargs: Backend())
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    answers = ["", "", "17", "موافق", "نعم", "17", "0", second_approval]
    if second_approval == "موافق":
        answers.append("نعم")
    answers.append("0")
    iterator = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(iterator))
    permissions = BoodaPermissionManager()
    permissions.add_permission(DESKTOP_PERMISSION, allowed=True, risk_level="high")
    approvals = BoodaApprovalManager(file_path=tmp_path / "approvals.json")
    manage_desktop(permissions, approvals, None)
    assert calls == (["launch_app", "type"] if second_approval == "موافق" else ["launch_app"])
    assert len(approvals.approvals) == len(calls)
