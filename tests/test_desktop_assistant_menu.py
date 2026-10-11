import time
import pytest
from core.approval_manager import BoodaApprovalManager
from core.permission_manager import BoodaPermissionManager
from core.desktop_control import DESKTOP_PERMISSION
from core.system_cli import manage_desktop


@pytest.mark.parametrize("confirmation,age,source_age,expected", [("موافق", 0, 0, ["assist", "search"]), ("موافقة", 0, 0, ["assist", "search"]), ("موافقه", 0, 0, ["assist", "search"]), ("لا", 0, 0, ["assist"]), (None, 31, 0, ["assist"]), (None, 0, 121, ["assist"])])
def test_model_proposal_requires_a_second_specific_approval(monkeypatch, confirmation, age, source_age, expected):
    calls = []
    class Backend:
        def target(self): return None
        def validate(self, operation, parameters): pass
        def perform(self, operation, parameters):
            calls.append((operation, parameters))
            if operation == "assist":
                return {"answer": "اقتراح فقط", "action": {"operation": "search", "parameters": {"query": "the exact reviewed query"}}, "proposed_at": time.monotonic() - age, "observed_at": time.monotonic() - source_age, "executed": False}
            return {"ok": True}
    monkeypatch.setattr("core.desktop_control.WindowsDesktopBackend", lambda **kwargs: Backend())
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    answers = ["", "", "16", "اسأل", "موافق", "15"]
    if confirmation is not None:
        answers.append(confirmation)
    answers.append("0")
    iterator = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(iterator))
    permissions = BoodaPermissionManager()
    permissions.add_permission(DESKTOP_PERMISSION, allowed=True, risk_level="high")
    manage_desktop(permissions, BoodaApprovalManager(), None)
    assert [operation for operation, parameters in calls] == expected
    if confirmation == "موافق":
        assert calls[-1][1] == {"query": "the exact reviewed query"}
