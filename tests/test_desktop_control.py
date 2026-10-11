import pytest
from core.desktop_control import BoodaDesktopController, DESKTOP_PERMISSION
from core.permission_manager import BoodaPermissionManager
from core.approval_manager import BoodaApprovalManager


class Backend:
    def __init__(self):
        self.window = {"window": 1, "title": "demo", "pid": 123}
        self.calls = []
    def target(self):
        return dict(self.window)
    def validate(self, op, p):
        pass
    def perform(self, op, p):
        self.calls.append((op, p))
        return {"ok": True}


def permissions(risk="high", allowed=True):
    manager = BoodaPermissionManager()
    manager.add_permission(DESKTOP_PERMISSION, allowed=allowed, risk_level=risk)
    return manager


def approve(task):
    manager = BoodaApprovalManager()
    key, approval = manager.create_approval(DESKTOP_PERMISSION, "test", task_id=task.task_id)
    manager.approve_approval(key)
    return approval


@pytest.mark.parametrize("operation", ["observe", "watch", "move", "click", "drag", "scroll", "type", "key", "open_url", "search", "transcribe", "launch_app", "play_media", "restore_window", "read_elements", "verify_text", "ocr_screen", "browser_open", "browser_read", "browser_click", "browser_fill"])
def test_every_action_requires_approval(operation):
    backend = Backend()
    controller = BoodaDesktopController(backend)
    task = controller.prepare(operation)
    assert controller.execute(task, permission_manager=permissions()) is None
    assert not backend.calls


def test_exactly_once_and_parameters_copied():
    backend = Backend()
    controller = BoodaDesktopController(backend)
    params = {"text": "مرحبا"}
    task = controller.prepare("type", params)
    params["text"] = "changed"
    approval = approve(task)
    assert controller.execute(task, permission_manager=permissions(), approval=approval) == {"ok": True}
    assert backend.calls == [("type", {"text": "مرحبا"})]
    with pytest.raises(ValueError):
        controller.execute(task, permission_manager=permissions(), approval=approval)


@pytest.mark.parametrize("failure", ["mutation", "expiry", "stop", "window", "wrong_approval", "low_permission", "disabled"])
def test_guarded_failures_never_send_input(failure):
    backend = Backend()
    clock = [0]
    controller = BoodaDesktopController(backend, clock=lambda: clock[0])
    task = controller.prepare("click", {"x": 20, "y": 20})
    approval = approve(task)
    pm = permissions()
    if failure == "mutation":
        task.metadata["parameters"]["x"] = 30
    if failure == "expiry":
        clock[0] = 121
    if failure == "stop":
        controller.stop()
    if failure == "window":
        backend.window["title"] = "other"
    if failure == "wrong_approval":
        approval = approve(controller.prepare("observe"))
    if failure == "low_permission":
        pm = permissions(risk="low")
    if failure == "disabled":
        pm = permissions(allowed=False)
    try:
        controller.execute(task, permission_manager=pm, approval=approval)
    except ValueError:
        pass
    assert not backend.calls


def test_no_shell_and_stop_invalidates_new_requests():
    controller = BoodaDesktopController(Backend())
    with pytest.raises(ValueError):
        controller.prepare("run_command", {"command": "anything"})
    controller.stop()
    with pytest.raises(ValueError):
        controller.prepare("observe")
