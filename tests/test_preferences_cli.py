import builtins

import core.main as main_module
from core.audit_log import BoodaAuditLog
from core.event_log import BoodaEventLog
from core.user_profile import BoodaUserProfileManager


def _cli_manager(tmp_path):
    audit = BoodaAuditLog(tmp_path / "audit.jsonl")
    events = BoodaEventLog(tmp_path / "events.jsonl")
    manager = BoodaUserProfileManager(
        tmp_path / "user_profile.json",
        audit_log=audit,
        event_log=events,
    )
    return manager, audit, events


def test_cli_lists_preferences_and_creates_project_scoped_value(
    tmp_path, monkeypatch, capsys
):
    manager, audit, events = _cli_manager(tmp_path)
    answers = iter([
        "4", "writing_tone", "مباشر وواضح", "2", "project-red", "1", "1",
        "3", "project-red", "3", "project-blue", "2", "0",
    ])
    monkeypatch.setattr(builtins, "input", lambda _prompt: next(answers))

    main_module.manage_preferences(manager)

    output = capsys.readouterr().out
    preference = next(
        item for item in manager.list_preferences()
        if item.key == "writing_tone"
    )
    assert "عرض كل التفضيلات" in output
    assert "عرض التفضيلات الفعالة فقط" in output
    assert "مباشر وواضح" in output
    assert "لا توجد تفضيلات مطابقة." in output
    assert preference.scope == "project"
    assert preference.scope_id == "project-red"
    assert preference.value == "مباشر وواضح"
    assert manager.effective_preferences(project_id="project-red")[
        "writing_tone"
    ].value == "مباشر وواضح"
    assert "writing_tone" not in manager.effective_preferences(
        project_id="project-blue"
    )
    assert any(event.action == "preference_created" for event in audit.get_events())
    assert events.get_events(entity_type="preference")


def test_cli_edits_disables_reactivates_promotes_and_deletes_preferences(
    tmp_path, monkeypatch, capsys
):
    manager, audit, events = _cli_manager(tmp_path)
    imported = manager.set_preference(
        "writing_tone",
        "مستورد",
        source="imported",
        scope="project",
        scope_id="project-1",
    )
    inferred = manager.set_preference(
        "study_format", "تمرين يومي", source="inferred"
    )
    delete_me = manager.set_preference("obsolete", "قيمة قديمة")
    answers = iter([
        "5", imported.id, "صياغة محدثة",
        "6", imported.id,
        "2",
        "7", imported.id,
        "9", inferred.id,
        "8", imported.id,
        "8", delete_me.id,
        "0",
    ])
    monkeypatch.setattr(builtins, "input", lambda _prompt: next(answers))

    main_module.manage_preferences(manager)

    output = capsys.readouterr().out
    assert "صياغة محدثة" not in output  # edits are confirmed without echoing input.
    assert manager.get_preference(imported.id) is None
    promoted = manager.get_preference(inferred.id)
    assert promoted.source == "explicit"
    assert promoted.active is True
    actions = {event.action for event in audit.get_events()}
    assert {
        "preference_updated",
        "preference_deactivated",
        "preference_activated",
        "preference_promoted",
        "preference_deleted",
    } <= actions
    assert {
        event["event_type"] for event in events.get_events(entity_type="preference")
    } >= {
        "preference_updated",
        "preference_deactivated",
        "preference_activated",
        "preference_promoted",
        "preference_deleted",
    }


def test_cli_adds_temporary_task_instruction_and_redacts_secret_like_values(
    tmp_path, monkeypatch, capsys
):
    manager, _, _ = _cli_manager(tmp_path)
    sensitive = manager.set_preference(
        "private_note", "sk-testSecretValue123456", source="explicit"
    )
    answers = iter([
        "2",
        "10", "task_instruction", "task-44", "راجعي التمرين قبل التسليم",
        "0",
    ])
    monkeypatch.setattr(builtins, "input", lambda _prompt: next(answers))

    main_module.manage_preferences(manager)

    output = capsys.readouterr().out
    task_instruction = next(
        item for item in manager.list_preferences()
        if item.key == "task_instruction"
    )
    assert "sk-testSecretValue123456" not in output
    assert "[REDACTED]" in output
    assert task_instruction.scope == "task"
    assert task_instruction.scope_id == "task-44"
    assert task_instruction.preference_type == "temporary"
    assert manager.get_preference(sensitive.id).value == "sk-testSecretValue123456"


def test_cli_rejects_secret_shaped_input_without_saving_it(
    tmp_path, monkeypatch, capsys
):
    manager, _, _ = _cli_manager(tmp_path)
    answers = iter([
        "4", "custom_note", "Bearer do-not-store-this-token", "0",
    ])
    monkeypatch.setattr(builtins, "input", lambda _prompt: next(answers))

    main_module.manage_preferences(manager)

    output = capsys.readouterr().out
    assert "do-not-store-this-token" not in output
    assert "رُفضت قيمة تبدو كبيانات سرية" in output
    assert not any(item.key == "custom_note" for item in manager.list_preferences())


def test_main_menu_exposes_profile_and_preferences_cli(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    answers = iter(["27", "0", "6"])
    monkeypatch.setattr(builtins, "input", lambda _prompt: next(answers))

    main_module.main()

    output = capsys.readouterr().out
    assert "27. إدارة الملف الشخصي والتفضيلات" in output
    assert "إدارة الملف الشخصي والتفضيلات:" in output


def test_preferences_cli_option_11_returns_to_main_menu_without_error(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    answers = iter(["27", "11", "6"])
    monkeypatch.setattr(builtins, "input", lambda _prompt: next(answers))

    main_module.main()

    output = capsys.readouterr().out
    assert "11. رجوع" in output
    assert "الاختيار غير صحيح." not in output
    assert "تم إغلاق Booda." in output
