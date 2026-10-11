from core.dialect_learning import add_dialect_correction, apply_dialect_corrections
from core.memory import BoodaStructuredMemoryStore


def test_user_confirmed_egyptian_phrase_is_applied_and_audited_locally(tmp_path):
    memory = BoodaStructuredMemoryStore(tmp_path / "memory.sqlite3")
    entry = add_dialect_correction(memory, "كيف حالك", "عاملة إيه")

    assert entry["status"] == "approved"
    assert apply_dialect_corrections(
        "يا بوده، كيف حالك؟", memory
    ) == "يا بوده، عاملة إيه؟"
    assert apply_dialect_corrections("كيف حالكِ", memory) == "كيف حالكِ"


def test_dialect_corrections_need_explicit_confirmation(tmp_path):
    memory = BoodaStructuredMemoryStore(tmp_path / "memory.sqlite3")

    try:
        memory.add_confirmed(
            "lesson", "egyptian_dialect:example", {"source_phrase": "x"},
            rationale="test", user_confirmed=False,
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("Unconfirmed dialect training was saved.")

    assert apply_dialect_corrections("x", memory) == "x"
