import json
from pathlib import Path

from core.task import BoodaTask
from core.persistence import JsonObjectStore


class BoodaTaskManager:
    def __init__(self, file_path=None, *, version_store=None, event_log=None):
        self.tasks = {}
        self.file_path = Path(file_path) if file_path else None
        self.version_store = version_store
        self.event_log = event_log
        self._load_tasks()

    def _load_tasks(self):
        if self.file_path is None or not self.file_path.exists():
            return

        with self.file_path.open("r", encoding="utf-8") as file:
            saved_tasks = json.load(file)

        if not isinstance(saved_tasks, dict):
            raise ValueError("Task state file must contain an object.")

        for task_id, data in saved_tasks.items():
            task = BoodaTask(
                task_id=task_id,
                title=data["title"],
                description=data.get("description", ""),
                status=data.get("status", "pending"),
                result=data.get("result"),
                depends_on=data.get("depends_on", ()),
                metadata=data.get("metadata", {}),
                project_id=data.get("project_id"),
                due_at=data.get("due_at"),
                goal_id=data.get("goal_id"),
            )
            self.tasks[task_id] = task
            task._on_change = lambda task_id=task_id: self._task_changed(task_id)

    def _save_tasks(self):
        if self.file_path is None:
            return

        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        saved_tasks = {}

        for task_id, task in self.tasks.items():
            saved_tasks[task_id] = {
                "title": task.title,
                "description": task.description,
                "status": task.status,
                "result": task.result,
                "depends_on": list(task.depends_on),
                "metadata": task.metadata,
                "project_id": task.project_id,
                "due_at": task.due_at,
                "goal_id": task.goal_id,
            }

        JsonObjectStore(self.file_path).save(saved_tasks)

    def add_task(self, task_id, title, description="", depends_on=None,
                 metadata=None, project_id=None, due_at=None, goal_id=None):
        return self.add_tasks([{
            "task_id": task_id,
            "title": title,
            "description": description,
            "depends_on": depends_on,
            "metadata": metadata,
            "project_id": project_id,
            "due_at": due_at,
            "goal_id": goal_id,
        }])[0]

    def add_tasks(self, task_specs):
        """Validate and persist a related task batch in one state-file write."""
        specs = list(task_specs)
        ids = [spec.get("task_id") for spec in specs]
        if any(not isinstance(task_id, str) or not task_id.strip() for task_id in ids):
            raise ValueError("Every task requires a non-empty string id.")
        if len(ids) != len(set(ids)):
            raise ValueError("Task ids in a batch must be unique.")
        for task_id in ids:
            if task_id in self.tasks:
                raise ValueError(f"Task already exists: {task_id}")
        created = [BoodaTask(**spec) for spec in specs]
        previous = self.tasks
        self.tasks = {**previous, **{task.task_id: task for task in created}}
        for task in created:
            task._on_change = lambda task_id=task.task_id: self._task_changed(task_id)
        try:
            self._save_tasks()
        except Exception:
            self.tasks = previous
            raise
        for task in created:
            self._record_task(task, "task_created")
        return created

    def _task_changed(self, task_id):
        self._save_tasks()
        task = self.tasks.get(task_id)
        if task is not None:
            self._record_task(task, "task_updated")

    def _record_task(self, task, event_type):
        snapshot = {
            "task_id": task.task_id,
            "title": task.title,
            "description": task.description,
            "status": task.status,
            "result": task.result,
            "depends_on": list(task.depends_on),
            "metadata": task.metadata,
            "goal_id": task.goal_id,
            "project_id": task.project_id,
            "due_at": task.due_at,
        }
        if self.version_store is not None:
            self.version_store.record("task", task.task_id, snapshot)
        if self.event_log is not None:
            self.event_log.record(
                event_type, entity_type="task", entity_id=task.task_id,
                details={"status": task.status, "goal_id": task.goal_id,
                         "project_id": task.project_id},
            )

    def get_task(self, task_id):
        return self.tasks.get(task_id)

    def list_tasks(self, *, project_id=None, status=None):
        return [
            task for task in self.tasks.values()
            if (project_id is None or task.project_id == project_id)
            and (status is None or task.status == status)
        ]

    def remove_task(self, task_id):
        task = self.tasks.pop(task_id, None)

        if task is not None:
            self._save_tasks()
            if self.version_store is not None:
                self.version_store.record("task", task_id, {"deleted": True})
            if self.event_log is not None:
                self.event_log.record(
                    "task_removed", entity_type="task", entity_id=task_id
                )

        return task
