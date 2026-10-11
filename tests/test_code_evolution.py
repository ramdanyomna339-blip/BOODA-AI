from pathlib import Path

import pytest

from core.approval_manager import BoodaApprovalManager
from core.audit_log import BoodaAuditLog
from core.code_evolution import BoodaCodeEvolution, CODE_PERMISSION
from core.permission_manager import BoodaPermissionManager


@pytest.fixture
def lab(tmp_path):
    (tmp_path / "core").mkdir()
    (tmp_path / "core/__init__.py").write_text("")
    (tmp_path / "core/example.py").write_text("def value():\n    return 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_example.py").write_text("from core.example import value\ndef test_value():\n    assert value() == 2\n")
    return BoodaCodeEvolution(tmp_path, database=tmp_path / "changes.sqlite3", lab=tmp_path / "lab")


def prepare(lab):
    return lab.prepare("core/example.py", "def value():\n    return 2\n", test_files=["tests/test_example.py"])


def approval(task_id):
    manager = BoodaApprovalManager()
    key, item = manager.create_approval(CODE_PERMISSION, "test", task_id=task_id)
    manager.approve_approval(key)
    return item


def permissions():
    manager = BoodaPermissionManager()
    manager.add_permission(CODE_PERMISSION, risk_level="high", allowed=True)
    return manager


def test_unreviewed_code_cannot_run_and_live_source_is_unchanged(lab):
    change = prepare(lab)
    with pytest.raises(ValueError):
        lab.validate(change["id"])
    assert "return 1" in (lab.root / "core/example.py").read_text()


def test_real_regression_apply_and_rollback(lab):
    change = prepare(lab)
    lab.mark_reviewed(change["id"], stage_digest=change["stage_digest"])
    validated = lab.validate(change["id"])
    assert validated["status"] == "validated", validated["validation"]
    audit = BoodaAuditLog(lab.root / "audit.jsonl")
    applied = lab.transition(change["id"], permission_manager=permissions(),
                             approval=approval(change["apply_task_id"]), audit_log=audit)
    assert applied.status == "completed" and "return 2" in (lab.root / "core/example.py").read_text()
    reverted = lab.transition(change["id"], rollback=True, permission_manager=permissions(),
                              approval=approval(change["rollback_task_id"]), audit_log=audit)
    assert reverted.status == "completed" and "return 1" in (lab.root / "core/example.py").read_text()
    assert lab.get(change["id"])["status"] == "reverted"


def test_failing_regression_prevents_application(lab):
    change = lab.prepare("core/example.py", "def value():\n    return 3\n", test_files=["tests/test_example.py"])
    lab.mark_reviewed(change["id"], stage_digest=change["stage_digest"])
    assert lab.validate(change["id"])["status"] == "validation_failed"
    with pytest.raises(ValueError):
        lab.transition(change["id"], permission_manager=permissions(), approval=None, audit_log=None)
    assert "return 1" in (lab.root / "core/example.py").read_text()


def test_changed_stage_cannot_use_previous_review(lab):
    change = prepare(lab)
    (lab.lab / change["id"] / "core/example.py").write_text("raise RuntimeError('changed')")
    with pytest.raises(ValueError):
        lab.mark_reviewed(change["id"], stage_digest=change["stage_digest"])


def test_protected_modules_and_test_option_injection_are_rejected(lab):
    for path in ["../core/example.py", "core/executor.py", "core/laptop.py"]:
        with pytest.raises(ValueError):
            lab.prepare(path, "x=1", test_files=["tests/test_example.py"])
    with pytest.raises(ValueError):
        lab.prepare("core/example.py", "x=1", test_files=["--override-ini=evil"])


def test_wrong_task_approval_cannot_apply_code(lab):
    change = prepare(lab)
    lab.mark_reviewed(change["id"], stage_digest=change["stage_digest"])
    assert lab.validate(change["id"])["status"] == "validated"
    task = lab.transition(change["id"], permission_manager=permissions(), approval=approval("wrong-task"), audit_log=None)
    assert task.status == "failed" and lab.get(change["id"])["status"] == "validated"
    assert "return 1" in (lab.root / "core/example.py").read_text()
