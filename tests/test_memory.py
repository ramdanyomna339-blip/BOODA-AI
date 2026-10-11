import pytest

from core.memory import (
    BoodaStructuredMemoryStore,
    JsonlBoodaMemory,
    MemoryConflictError,
)
from core.planning import BoodaGoal


def test_jsonl_memory_persists_and_filters_entries_by_goal(tmp_path):
    path = tmp_path / "agent_memory.jsonl"
    memory = JsonlBoodaMemory(path)
    memory.remember("goal-a", {"event": "received", "intent": "Write"})
    memory.remember("goal-b", {"event": "received", "intent": "Research"})
    memory.remember("goal-a", {"event": "completed"})

    reopened = JsonlBoodaMemory(path)

    assert reopened.recall("goal-a") == [
        {"event": "received", "intent": "Write"},
        {"event": "completed"},
    ]
    assert reopened.recall("missing") == []


def test_legacy_conversation_turns_are_not_recalled_into_planner_context(tmp_path):
    from core.planning import BoodaGoal

    path = tmp_path / "legacy.jsonl"
    memory = JsonlBoodaMemory(path)
    memory.remember(
        "goal",
        {
            "event": "conversation_turn",
            "message": "private text",
            "response": "private reply",
        },
    )

    context = memory.recall_context(BoodaGoal("goal", "continue"))

    assert context == {"goal_events": []}
    assert "private text" in path.read_text(encoding="utf-8")


def test_confirmed_memory_persists_and_isolated_by_project_and_client(tmp_path):
    path = tmp_path / "structured.sqlite3"
    memory = BoodaStructuredMemoryStore(path)
    memory.add_confirmed(
        "preference", "language", "العربية المصرية",
        rationale="أكدت المستخدمة ذلك", user_confirmed=True,
    )
    memory.add_confirmed(
        "project", "campaign_goal", "زيادة التسجيلات",
        scope="project", scope_id="campaign-a",
        rationale="قرار المشروع", user_confirmed=True,
    )
    memory.add_confirmed(
        "client", "brand_tone", "رسمي",
        scope="client", scope_id="client-a",
        rationale="اعتماد العميل", user_confirmed=True,
    )
    reopened = BoodaStructuredMemoryStore(path)

    project_context = reopened.recall_context(
        BoodaGoal("g", "حملة التسجيلات", {"project_id": "campaign-a"})
    )
    other_project_context = reopened.recall_context(
        BoodaGoal("g2", "حملة التسجيلات", {"project_id": "campaign-b"})
    )
    client_context = reopened.recall_context(
        BoodaGoal("g3", "كتابة نص للعميل", {"client_id": "client-a"})
    )

    assert project_context["approved_memory"]["preference"][0]["value"] == "العربية المصرية"
    assert project_context["approved_memory"]["project"][0]["value"] == "زيادة التسجيلات"
    assert "client" not in project_context["approved_memory"]
    assert "project" not in other_project_context["approved_memory"]
    assert client_context["approved_memory"]["client"][0]["value"] == "رسمي"


def test_proposals_are_not_recalled_as_confirmed_before_approval(tmp_path):
    memory = BoodaStructuredMemoryStore(tmp_path / "memory.sqlite3")
    proposal = memory.propose(
        "lesson", "posting_time", "جرّبي النشر مساءً",
        rationale="استنتاج غير مؤكد",
    )
    context = memory.recall_context(BoodaGoal("g", "النشر"))

    assert context["approved_memory"] == {}
    assert context["pending_memory_proposals"][0]["entry_id"] == proposal["entry_id"]
    with pytest.raises(PermissionError, match="confirmation"):
        memory.approve(proposal["entry_id"])
    assert memory.get_entry(proposal["entry_id"])["status"] == "proposed"

    memory.approve(proposal["entry_id"], user_confirmed=True)
    approved_context = memory.recall_context(BoodaGoal("g2", "النشر"))
    assert approved_context["approved_memory"]["lesson"][0]["status"] == "approved"
    assert approved_context["pending_memory_proposals"] == []


def test_conflicts_require_explicit_correction_and_delete_is_durable(tmp_path):
    memory_path = tmp_path / "memory.sqlite3"
    memory = BoodaStructuredMemoryStore(memory_path)
    original = memory.add_confirmed(
        "fact", "preferred_language", "Arabic",
        rationale="User stated", user_confirmed=True,
    )
    proposal = memory.propose(
        "fact", "preferred_language", "English", rationale="Possible update",
    )
    with pytest.raises(MemoryConflictError, match="correct it"):
        memory.approve(proposal["entry_id"], user_confirmed=True)

    corrected = memory.correct(
        original["entry_id"], "Egyptian Arabic",
        rationale="User corrected prior statement",
        user_confirmed=True,
    )
    assert memory.get_entry(original["entry_id"])["status"] == "superseded"
    assert memory.recall_context(BoodaGoal("g", "language"))[
        "approved_memory"
    ]["fact"][0]["value"] == "Egyptian Arabic"
    assert memory.delete(original["entry_id"])
    assert memory.get_entry(corrected["entry_id"])["supersedes_id"] is None
    assert memory.delete(corrected["entry_id"])
    assert BoodaStructuredMemoryStore(memory_path).get_entry(corrected["entry_id"]) is None


def test_invalid_or_sensitive_memory_is_rejected_without_storage(tmp_path):
    memory = BoodaStructuredMemoryStore(tmp_path / "memory.sqlite3")
    with pytest.raises(PermissionError):
        memory.add_confirmed(
            "fact", "language", "Arabic", rationale="User stated",
        )
    with pytest.raises(ValueError, match="Sensitive credentials"):
        memory.add_confirmed(
            "fact", "api_key", "not-to-store",
            rationale="User stated", user_confirmed=True,
        )
    with pytest.raises(ValueError, match="valid JSON"):
        memory.add_confirmed(
            "fact", "bad", object(),
            rationale="Invalid value", user_confirmed=True,
        )
    with pytest.raises(ValueError, match="expiry"):
        memory.add_confirmed(
            "temporary", "campaign_status", "active",
            rationale="Temporary", user_confirmed=True,
        )
    with pytest.raises(ValueError, match="Sensitive credentials"):
        memory.add_confirmed(
            "fact", "integration", "configured",
            rationale="api_key=sample-secret-value",
            user_confirmed=True,
        )
    assert memory.list_entries() == []


def test_memory_audit_omits_values_and_reports_post_commit_audit_failure(tmp_path):
    class AuditCapture:
        def __init__(self):
            self.events = []

        def record(self, **event):
            self.events.append(event)

    audit = AuditCapture()
    path = tmp_path / "memory.sqlite3"
    memory = BoodaStructuredMemoryStore(path, audit_log=audit)
    entry = memory.add_confirmed(
        "fact", "favorite_color", "blue",
        rationale="User confirmed the color",
        user_confirmed=True,
    )
    assert audit.events[0]["action"] == "memory_approved"
    assert "blue" not in str(audit.events[0])
    assert "User confirmed" not in str(audit.events[0])

    class BrokenAudit:
        def record(self, **event):
            assert event
            raise OSError("audit unavailable")

    failing = BoodaStructuredMemoryStore(path, audit_log=BrokenAudit())
    with pytest.raises(RuntimeError, match="change was committed"):
        failing.correct(
            entry["entry_id"], "green",
            rationale="User corrected the color",
            user_confirmed=True,
        )
    assert failing.get_entry(entry["entry_id"])["status"] == "superseded"
    assert len(failing.list_entries()) == 2


def test_temporary_memory_expires_and_unapproved_legacy_jsonl_facts_are_not_recalled(
    tmp_path,
):
    legacy_path = tmp_path / "memory.jsonl"
    legacy = JsonlBoodaMemory(legacy_path)
    legacy_path.write_text(
        '{"record_type":"fact","scope":"user","key":"unsafe","value":"unverified"}\n',
        encoding="utf-8",
    )
    memory = BoodaStructuredMemoryStore(tmp_path / "memory.sqlite3")
    memory.add_confirmed(
        "temporary", "campaign_note", "old note",
        rationale="Short-lived", user_confirmed=True,
        expires_at="2000-01-01T00:00:00+00:00",
    )
    legacy_context = legacy.recall_context(BoodaGoal("g", "campaign"))
    context = memory.recall_context(BoodaGoal("g", "campaign"))

    assert "user_facts" not in legacy_context
    assert context["approved_memory"] == {}
