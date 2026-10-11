"""Typed records for local, user-governed system evolution."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now():
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ExperienceRecord:
    task_id: str
    goal: str
    inputs_summary: str
    result_summary: str
    outcome: str
    metrics: dict[str, Any] = field(default_factory=dict)
    lessons: tuple[str, ...] = ()
    created_at: str = field(default_factory=utc_now)
    experience_id: str = ""


@dataclass(frozen=True)
class CapabilityGap:
    name: str
    description: str
    detected_from: str
    required_tools: tuple[str, ...] = ()
    status: str = "detected"
    gap_id: str = ""
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class ImprovementProposal:
    title: str
    problem: str
    proposed_solution: str
    expected_benefit: str
    risks: str
    cost: str
    status: str = "proposed"
    proposal_id: str = ""
    created_at: str = field(default_factory=utc_now)
    sandbox_report: str | None = None


@dataclass(frozen=True)
class EvaluationRecord:
    quality: float | None
    reliability: float | None
    speed: float | None
    cost: float | None
    privacy: float | None
    notes: str
    experience_id: str
    evaluation_id: str = ""
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class ChangeLogRecord:
    component: str
    old_version: int
    new_version: int
    reason: str
    approval_status: str
    changed_at: str = field(default_factory=utc_now)
    change_id: str = ""


@dataclass(frozen=True)
class KnowledgeRecord:
    content: str
    source: str
    knowledge_id: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)
