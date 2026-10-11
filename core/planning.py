"""Goal and plan types used by Booda's decision layer."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BoodaGoal:
    goal_id: str
    intent: str
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.goal_id.strip():
            raise ValueError("Goal id must not be empty.")
        if not self.intent.strip():
            raise ValueError("Goal intent must not be empty.")


@dataclass(frozen=True)
class PlanStep:
    task_id: str
    title: str
    description: str = ""
    capability: str | None = None
    depends_on: tuple[str, ...] = ()
    permission_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    due_at: str | None = None

    def __post_init__(self):
        if not self.task_id.strip() or not self.title.strip():
            raise ValueError("Plan steps require an id and title.")
        object.__setattr__(self, "depends_on", tuple(self.depends_on))
        object.__setattr__(self, "metadata", dict(self.metadata))
        if self.due_at is not None:
            from core.scheduler import parse_due_at

            parse_due_at(self.due_at)


@dataclass(frozen=True)
class BoodaPlan:
    goal_id: str
    steps: tuple[PlanStep, ...]
    plan_id: str = "plan-1"

    def __post_init__(self):
        object.__setattr__(self, "steps", tuple(self.steps))
        ids = {step.task_id for step in self.steps}
        if len(ids) != len(self.steps):
            raise ValueError("Plan task ids must be unique.")
        for step in self.steps:
            from core.dataflow import validate_bindings
            validate_bindings(step)
            missing = set(step.depends_on) - ids
            if missing:
                raise ValueError(f"Unknown dependencies for {step.task_id}: {sorted(missing)}")
            if step.task_id in step.depends_on:
                raise ValueError("A task cannot depend on itself.")
        self._validate_acyclic()

    def _validate_acyclic(self):
        visited, active = set(), set()

        def visit(task_id):
            if task_id in active:
                raise ValueError("Plan dependencies must not contain cycles.")
            if task_id in visited:
                return
            active.add(task_id)
            step = next(item for item in self.steps if item.task_id == task_id)
            for dependency in step.depends_on:
                visit(dependency)
            active.remove(task_id)
            visited.add(task_id)

        for step in self.steps:
            visit(step.task_id)
