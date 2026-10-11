"""Persistent catalog of files and other outputs produced for Booda work."""

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from core.persistence import JsonObjectStore


class BoodaArtifactManager:
    def __init__(self, file_path="outputs/artifacts.json", *, event_log=None,
                 version_store=None):
        self.store = JsonObjectStore(file_path)
        self.event_log = event_log
        self.version_store = version_store
        self.artifacts = self.store.load()

    def register(self, path, *, artifact_id=None, kind="file", title=None,
                 goal_id=None, project_id=None, task_id=None, metadata=None):
        artifact_path = Path(path)
        if not artifact_path.exists() or not artifact_path.is_file():
            raise FileNotFoundError(f"Artifact file does not exist: {artifact_path}")
        artifact_id = artifact_id or f"artifact-{uuid4().hex}"
        if artifact_id in self.artifacts:
            raise ValueError(f"Artifact already registered: {artifact_id}")
        artifact = {
            "artifact_id": artifact_id,
            "path": str(artifact_path.resolve()),
            "kind": kind,
            "title": title or artifact_path.name,
            "goal_id": goal_id,
            "project_id": project_id,
            "task_id": task_id,
            "metadata": dict(metadata or {}),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.artifacts[artifact_id] = artifact
        self.store.save(self.artifacts)
        if self.version_store is not None:
            self.version_store.record("artifact", artifact_id, artifact)
        if self.event_log is not None:
            self.event_log.record(
                "artifact_registered", entity_type="artifact", entity_id=artifact_id,
                details={"kind": kind, "path": artifact["path"], "task_id": task_id},
            )
        return dict(artifact)

    def get(self, artifact_id):
        item = self.artifacts.get(artifact_id)
        return dict(item) if item is not None else None

    def list(self, *, goal_id=None, project_id=None, task_id=None, kind=None):
        return [
            dict(item) for item in self.artifacts.values()
            if (goal_id is None or item.get("goal_id") == goal_id)
            and (project_id is None or item.get("project_id") == project_id)
            and (task_id is None or item.get("task_id") == task_id)
            and (kind is None or item.get("kind") == kind)
        ]
