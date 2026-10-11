"""Persistent project management, separate from task execution state."""

import json
from pathlib import Path

from core.project import BoodaProject


class BoodaProjectManager:
    def __init__(self, file_path=None, *, version_store=None, event_log=None):
        self.projects = {}
        self.file_path = Path(file_path) if file_path else None
        self.version_store = version_store
        self.event_log = event_log
        self._load_projects()

    def _load_projects(self):
        if self.file_path is None or not self.file_path.exists():
            return
        with self.file_path.open("r", encoding="utf-8") as file:
            saved_projects = json.load(file)
        if not isinstance(saved_projects, dict):
            raise ValueError("Project state file must contain an object.")
        for project_id, data in saved_projects.items():
            if not isinstance(data, dict):
                raise ValueError(f"Project {project_id} must contain an object.")
            self.projects[project_id] = BoodaProject(
                project_id=project_id,
                title=data["title"],
                description=data.get("description", ""),
                goal_id=data.get("goal_id"),
                status=data.get("status", "active"),
                due_at=data.get("due_at"),
                metadata=data.get("metadata", {}),
            )

    def _save_projects(self):
        if self.file_path is None:
            return
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            project_id: {
                "title": project.title,
                "description": project.description,
                "goal_id": project.goal_id,
                "status": project.status,
                "due_at": project.due_at,
                "metadata": project.metadata,
            }
            for project_id, project in self.projects.items()
        }
        temporary_path = Path(str(self.file_path) + ".tmp")
        with temporary_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2, default=str)
        temporary_path.replace(self.file_path)

    def add_project(self, project_id, title, description="", *, goal_id=None,
                    due_at=None, metadata=None):
        if project_id in self.projects:
            raise ValueError(f"Project already exists: {project_id}")
        project = BoodaProject(
            project_id=project_id,
            title=title,
            description=description,
            goal_id=goal_id,
            due_at=due_at,
            metadata=metadata or {},
        )
        self.projects[project_id] = project
        self._save_projects()
        self._record(project, "project_created")
        return project

    def get_project(self, project_id):
        return self.projects.get(project_id)

    def list_projects(self, *, status=None, goal_id=None):
        return [
            project for project in self.projects.values()
            if (status is None or project.status == status)
            and (goal_id is None or project.goal_id == goal_id)
        ]

    def update_project(self, project_id, **changes):
        project = self.get_project(project_id)
        if project is None:
            return None
        allowed = {"title", "description", "goal_id", "status", "due_at", "metadata"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"Unknown project fields: {sorted(unknown)}")
        values = {
            "project_id": project.project_id,
            "title": project.title,
            "description": project.description,
            "goal_id": project.goal_id,
            "status": project.status,
            "due_at": project.due_at,
            "metadata": project.metadata,
        }
        values.update(changes)
        updated = BoodaProject(**values)
        self.projects[project_id] = updated
        self._save_projects()
        self._record(updated, "project_updated")
        return updated

    def _record(self, project, event_type):
        snapshot = {
            "project_id": project.project_id,
            "title": project.title,
            "description": project.description,
            "goal_id": project.goal_id,
            "status": project.status,
            "due_at": project.due_at,
            "metadata": project.metadata,
        }
        if self.version_store is not None:
            self.version_store.record("project", project.project_id, snapshot)
        if self.event_log is not None:
            self.event_log.record(
                event_type, entity_type="project", entity_id=project.project_id,
                details={"status": project.status, "goal_id": project.goal_id},
            )
