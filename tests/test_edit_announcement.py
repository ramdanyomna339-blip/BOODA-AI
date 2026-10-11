import pytest

from core.file_action import update_saved_announcement


def test_edit_updates_announcement_and_keeps_backup(tmp_path):
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()

    announcement = output_dir / "announcement-task-002.txt"
    old_content = "العنوان: اعلان\n\nالوصف:\nبيع\n"
    announcement.write_text(old_content, encoding="utf-8")

    updated_path, backup_path = update_saved_announcement(
        announcement,
        new_title="إعلان جديد",
        new_description="عرض خاص",
        output_dir=output_dir,
    )

    assert updated_path.read_text(encoding="utf-8") == (
        "العنوان: إعلان جديد\n\nالوصف:\nعرض خاص\n"
    )
    assert backup_path.read_text(encoding="utf-8") == old_content


def test_edit_rejects_file_outside_outputs_folder(tmp_path):
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()

    outside_file = tmp_path / "outside.txt"
    outside_file.write_text(
        "العنوان: اعلان\n\nالوصف:\nبيع\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        update_saved_announcement(
            outside_file,
            new_title="عنوان جديد",
            output_dir=output_dir,
        )