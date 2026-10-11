import re
import shutil
from pathlib import Path


def _format_announcement(title, description):
    description = description or "لا يوجد وصف"
    return f"العنوان: {title}\n\nالوصف:\n{description}\n"


def save_task_content(task, output_dir="outputs"):
    output_folder = Path(output_dir)
    output_folder.mkdir(parents=True, exist_ok=True)

    safe_task_id = re.sub(r"[^\w-]", "_", task.task_id)
    safe_task_id = safe_task_id.strip("_") or "task"

    base_name = f"announcement-{safe_task_id}"
    output_path = output_folder / f"{base_name}.txt"

    number = 2
    while output_path.exists():
        output_path = output_folder / f"{base_name}-{number}.txt"
        number += 1

    content = _format_announcement(task.title, task.description)
    output_path.write_text(content, encoding="utf-8")
    return str(output_path)


def save_plan_artifact(goal_id, goal, tasks, output_dir="outputs"):
    output_folder = Path(output_dir) / "plans"
    output_folder.mkdir(parents=True, exist_ok=True)

    safe_goal_id = re.sub(r"[^\w-]", "_", goal_id).strip("_") or "goal"
    base_name = f"plan-{safe_goal_id}"
    output_path = output_folder / f"{base_name}.md"
    number = 2
    while output_path.exists():
        output_path = output_folder / f"{base_name}-{number}.md"
        number += 1

    lines = [f"# خطة: {goal}", "", f"معرّف الهدف: `{goal_id}`", ""]
    for index, task in enumerate(tasks, start=1):
        lines.extend([
            f"## {index}. {task.title}",
            "",
            task.description,
            "",
            f"معرّف الخطوة: `{task.task_id}`",
            "",
        ])
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return str(output_path)


def list_saved_announcements(output_dir="outputs"):
    output_folder = Path(output_dir)

    if not output_folder.exists() or not output_folder.is_dir():
        return []

    return sorted(
        [
            path
            for path in output_folder.iterdir()
            if path.is_file() and path.suffix.lower() == ".txt"
        ],
        key=lambda path: path.name.casefold(),
    )


def read_saved_announcement(file_path):
    path = Path(file_path)
    content = path.read_text(encoding="utf-8")

    title_marker = "العنوان: "
    description_marker = "\n\nالوصف:\n"

    if not content.startswith(title_marker) or description_marker not in content:
        raise ValueError("صيغة ملف الإعلان غير صحيحة.")

    title_part, description = content.split(description_marker, 1)

    return {
        "title": title_part[len(title_marker):],
        "description": description.rstrip("\r\n"),
    }


def update_saved_announcement(
    file_path,
    new_title=None,
    new_description=None,
    output_dir="outputs",
):
    output_folder = Path(output_dir).resolve()
    path = Path(file_path).resolve()

    if path.parent != output_folder or path.suffix.lower() != ".txt":
        raise ValueError("يمكن تعديل ملفات الإعلانات داخل مجلد outputs فقط.")

    if not path.is_file():
        raise FileNotFoundError("ملف الإعلان غير موجود.")

    current = read_saved_announcement(path)
    title = new_title if new_title is not None else current["title"]
    description = (
        new_description
        if new_description is not None
        else current["description"]
    )

    backup_path = path.with_name(path.name + ".bak")
    number = 2

    while backup_path.exists():
        backup_path = path.with_name(f"{path.name}.{number}.bak")
        number += 1

    shutil.copy2(path, backup_path)

    temporary_path = path.with_name(path.name + ".tmp")
    temporary_path.write_text(
        _format_announcement(title, description),
        encoding="utf-8",
    )
    temporary_path.replace(path)

    return path, backup_path