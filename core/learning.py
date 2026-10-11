"""Persistent learning paths with lesson progress and assessment history."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from core.persistence import JsonObjectStore


LEARNING_STATUSES = {"not_started", "in_progress", "completed"}


@dataclass(frozen=True)
class LearningUnit:
    unit_id: str
    title: str
    description: str = ""
    status: str = "not_started"
    metadata: dict[str, Any] | None = None


class BoodaLearningManager:
    def __init__(self, file_path="knowledge/learning_paths.json", *,
                 version_store=None, event_log=None):
        self.store = JsonObjectStore(file_path)
        self.version_store = version_store
        self.event_log = event_log
        self.paths = self.store.load()
        for path in self.paths.values():
            path.setdefault("project_submissions", [])
            self._validate_path(path)

    @staticmethod
    def _validate_path(path):
        if path.get("status") not in LEARNING_STATUSES:
            raise ValueError("Invalid learning path status.")
        units = path.get("units", [])
        ids = [unit["unit_id"] for unit in units]
        if len(ids) != len(set(ids)):
            raise ValueError("Learning unit ids must be unique within a path.")
        if any(unit.get("status") not in LEARNING_STATUSES for unit in units):
            raise ValueError("Invalid learning unit status.")

    def _save(self):
        self.store.save(self.paths)

    def add_path(self, title, units, *, path_id=None, goal_id=None, metadata=None):
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Learning path title must not be empty.")
        path_id = path_id or f"learning-{uuid4().hex}"
        if path_id in self.paths:
            raise ValueError(f"Learning path already exists: {path_id}")
        normalized = []
        for index, unit in enumerate(units, start=1):
            if isinstance(unit, LearningUnit):
                item = {
                    "unit_id": unit.unit_id,
                    "title": unit.title,
                    "description": unit.description,
                    "status": unit.status,
                    "metadata": dict(unit.metadata or {}),
                    "order": index,
                }
            else:
                item = {
                    "unit_id": unit.get("unit_id") or f"unit-{index}",
                    "title": unit.get("title", "").strip(),
                    "description": unit.get("description", ""),
                    "status": unit.get("status", "not_started"),
                    "metadata": dict(unit.get("metadata", {})),
                    "order": index,
                }
            if not item["title"].strip():
                raise ValueError("Every learning unit requires a title.")
            normalized.append(item)
        path = {
            "path_id": path_id,
            "title": title.strip(),
            "goal_id": goal_id,
            "status": "not_started" if normalized else "completed",
            "units": normalized,
            "assessments": [],
            "project_submissions": [],
            "metadata": dict(metadata or {}),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._validate_path(path)
        self.paths[path_id] = path
        self._save()
        self._record(path_id, "learning_path_created")
        return self.get_path(path_id)

    def get_path(self, path_id):
        path = self.paths.get(path_id)
        if path is None:
            return None
        result = dict(path)
        result["units"] = [dict(unit) for unit in path["units"]]
        result["assessments"] = [dict(item) for item in path["assessments"]]
        result["project_submissions"] = [
            dict(item) for item in path.get("project_submissions", [])
        ]
        completed = sum(unit["status"] == "completed" for unit in path["units"])
        result["progress"] = completed / len(path["units"]) if path["units"] else 1.0
        return result

    def list_paths(self, *, goal_id=None, status=None):
        return [
            self.get_path(path_id) for path_id, path in self.paths.items()
            if (goal_id is None or path.get("goal_id") == goal_id)
            and (status is None or path.get("status") == status)
        ]

    def update_unit_status(self, path_id, unit_id, status):
        if status not in LEARNING_STATUSES:
            raise ValueError("Invalid learning unit status.")
        path = self.paths.get(path_id)
        if path is None:
            return None
        unit = next((item for item in path["units"] if item["unit_id"] == unit_id), None)
        if unit is None:
            return None
        unit["status"] = status
        states = [item["status"] for item in path["units"]]
        path["status"] = (
            "completed" if states and all(item == "completed" for item in states)
            else "in_progress" if any(item != "not_started" for item in states)
            else "not_started"
        )
        self._save()
        self._record(path_id, "learning_unit_status_changed", {"unit_id": unit_id, "status": status})
        return self.get_path(path_id)

    def record_assessment(self, path_id, *, score, feedback="", unit_id=None):
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 100:
            raise ValueError("Assessment score must be between 0 and 100.")
        path = self.paths.get(path_id)
        if path is None:
            return None
        if unit_id is not None and not any(u["unit_id"] == unit_id for u in path["units"]):
            raise ValueError(f"Unknown learning unit: {unit_id}")
        path["assessments"].append({
            "assessment_id": f"assessment-{uuid4().hex}",
            "unit_id": unit_id,
            "score": score,
            "feedback": feedback,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        })
        self._save()
        self._record(path_id, "learning_assessment_recorded", {"unit_id": unit_id, "score": score})
        return dict(path["assessments"][-1])

    def record_project_submission(self, path_id, *, unit_id, prompt, submission):
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Project prompt must not be empty.")
        if not isinstance(submission, str) or not submission.strip():
            raise ValueError("Project submission must not be empty.")
        if len(submission) > 10000:
            raise ValueError("Project submission must not exceed 10,000 characters.")
        path = self.paths.get(path_id)
        if path is None:
            return None
        if not any(unit["unit_id"] == unit_id for unit in path["units"]):
            raise ValueError(f"Unknown learning unit: {unit_id}")
        project = {
            "submission_id": f"learning-project-{uuid4().hex}",
            "unit_id": unit_id,
            "prompt": prompt.strip(),
            "submission": submission.strip(),
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }
        path.setdefault("project_submissions", []).append(project)
        self._save()
        self._record(
            path_id,
            "learning_project_submitted",
            {
                "unit_id": unit_id,
                "submission_id": project["submission_id"],
                "character_count": len(project["submission"]),
            },
        )
        return dict(project)

    def _record(self, path_id, event_type, details=None):
        path = self.paths[path_id]
        if self.version_store is not None:
            self.version_store.record("learning_path", path_id, path)
        if self.event_log is not None:
            self.event_log.record(
                event_type, entity_type="learning_path", entity_id=path_id,
                details=details,
            )
