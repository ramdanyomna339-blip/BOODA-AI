"""Persistent goal records and lifecycle management."""

from dataclasses import dataclass
from datetime import datetime, timezone

from core.persistence import JsonObjectStore
from core.planning import BoodaGoal


GOAL_STATUSES = {"active", "paused", "completed", "cancelled"}


@dataclass(frozen=True)
class BoodaGoalRecord:
    goal: BoodaGoal
    status: str = "active"
    project_id: str | None = None
    created_at: str = ""
    updated_at: str = ""


class BoodaGoalManager:
    def __init__(self, file_path="memory/goals.json", *, version_store=None, event_log=None):
        self.store = JsonObjectStore(file_path)
        self.version_store = version_store
        self.event_log = event_log
        self.goals = {}
        for goal_id, data in self.store.load().items():
            goal = BoodaGoal(goal_id, data["intent"], data.get("context", {}))
            self.goals[goal_id] = BoodaGoalRecord(
                goal=goal,
                status=data.get("status", "active"),
                project_id=data.get("project_id"),
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
            )
            self._validate_status(self.goals[goal_id].status)

    @staticmethod
    def _validate_status(status):
        if status not in GOAL_STATUSES:
            raise ValueError(f"Goal status must be one of {sorted(GOAL_STATUSES)}.")

    def _save(self):
        self.store.save({
            goal_id: {
                "intent": record.goal.intent,
                "context": record.goal.context,
                "status": record.status,
                "project_id": record.project_id,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }
            for goal_id, record in self.goals.items()
        })

    def add_goal(self, goal, *, project_id=None):
        if not isinstance(goal, BoodaGoal):
            raise TypeError("goal must be a BoodaGoal.")
        if goal.goal_id in self.goals:
            raise ValueError(f"Goal already exists: {goal.goal_id}")
        now = datetime.now(timezone.utc).isoformat()
        record = BoodaGoalRecord(goal, "active", project_id, now, now)
        self.goals[goal.goal_id] = record
        self._save()
        self._record(record, "goal_created")
        return record

    def get_goal(self, goal_id):
        return self.goals.get(goal_id)

    def list_goals(self, *, status=None, project_id=None):
        if status is not None:
            self._validate_status(status)
        return [
            record for record in self.goals.values()
            if (status is None or record.status == status)
            and (project_id is None or record.project_id == project_id)
        ]

    def update_status(self, goal_id, status):
        record = self.get_goal(goal_id)
        if record is None:
            return None
        self._validate_status(status)
        updated = BoodaGoalRecord(
            record.goal, status, record.project_id, record.created_at,
            datetime.now(timezone.utc).isoformat(),
        )
        self.goals[goal_id] = updated
        self._save()
        self._record(updated, "goal_status_changed")
        return updated

    def _record(self, record, event_type):
        snapshot = {
            "goal_id": record.goal.goal_id,
            "intent": record.goal.intent,
            "context": record.goal.context,
            "status": record.status,
            "project_id": record.project_id,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }
        if self.version_store is not None:
            self.version_store.record("goal", record.goal.goal_id, snapshot)
        if self.event_log is not None:
            self.event_log.record(
                event_type, entity_type="goal", entity_id=record.goal.goal_id,
                details={"status": record.status, "project_id": record.project_id},
            )
