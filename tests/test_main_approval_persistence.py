import builtins

import core.main as main_module
from core.audit_log import BoodaAuditLog


def test_main_menu_keeps_approval_after_reopening(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.chdir(tmp_path)

    audit_log = BoodaAuditLog(tmp_path / "audit_log.jsonl")
    answers = iter(
        [
            "7",
            "spend_money",
            "Yomna",
            "Yomna",
            "task-approval-001",
            "Approved purchase.",
            "8",
            "approval-1",
            "Yomna",
            "6",
            "10",
            "6",
        ]
    )

    monkeypatch.setattr(
        main_module,
        "BoodaAuditLog",
        lambda: audit_log,
    )
    monkeypatch.setattr(
        builtins,
        "input",
        lambda prompt: next(answers),
    )

    main_module.main()
    main_module.main()

    output = capsys.readouterr().out

    assert "تم إنشاء الموافقة: approval-1" in output
    assert "تم اعتماد الموافقة: approval-1" in output
    assert "approval-1: spend_money" in output
    assert "الحالة: معتمدة" in output