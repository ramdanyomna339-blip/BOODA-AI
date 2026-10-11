"""User-confirmed Egyptian Arabic phrase corrections for local speech."""

import hashlib
import re


_KEY_PREFIX = "egyptian_dialect:"


def add_dialect_correction(memory, source_phrase, egyptian_phrase):
    source_phrase = memory._require_safe_text(source_phrase, "source_phrase")
    egyptian_phrase = memory._require_safe_text(egyptian_phrase, "egyptian_phrase")
    key = _KEY_PREFIX + hashlib.sha256(source_phrase.casefold().encode("utf-8")).hexdigest()
    return memory.add_confirmed(
        "lesson",
        key,
        {"source_phrase": source_phrase, "egyptian_phrase": egyptian_phrase},
        rationale="تصحيح لهجة مصرية أدخلته المستخدمة بنفسها",
        user_confirmed=True,
        actor="dialect-coach",
    )


def list_dialect_corrections(memory):
    return [
        entry for entry in memory.list_entries(status="approved", scope="user")
        if entry["category"] == "lesson" and entry["memory_key"].startswith(_KEY_PREFIX)
        and isinstance(entry["value"], dict)
    ]


def apply_dialect_corrections(text, memory):
    """Apply only explicit user-approved phrase substitutions, longest first."""
    if not isinstance(text, str) or not text or memory is None:
        return text
    entries = sorted(
        list_dialect_corrections(memory),
        key=lambda entry: len(entry["value"].get("source_phrase", "")),
        reverse=True,
    )
    for entry in entries:
        source = entry["value"].get("source_phrase", "").strip()
        target = entry["value"].get("egyptian_phrase", "").strip()
        if source and target:
            text = re.sub(
                rf"(?<![\w\u064b-\u065f\u0670]){re.escape(source)}"
                rf"(?![\w\u064b-\u065f\u0670])",
                lambda _match: target,
                text,
                flags=re.IGNORECASE,
            )
    return text
