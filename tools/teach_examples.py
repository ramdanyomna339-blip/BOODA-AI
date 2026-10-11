"""Import attributed teacher examples as private reference data, never authority."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from core.knowledge_base import BoodaLocalKnowledgeBase
from core.memory import BoodaStructuredMemoryStore


def read_teacher_pack(source):
    source = Path(source)
    if source.stat().st_size > 2_000_000:
        raise ValueError("Teacher pack is too large.")
    raw = source.read_bytes()
    if len(raw) > 2_000_000:
        raise ValueError("Teacher pack is too large.")
    pack = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(pack, dict) or set(pack) != {"teacher", "scope", "examples"}:
        raise ValueError("Teacher pack requires teacher, scope and examples.")
    if pack["teacher"] not in {"Codex", "Manus", "Meta", "Gemini", "user"}:
        raise ValueError("Unknown declared teacher.")
    scope = pack["scope"]
    if not isinstance(scope, dict) or set(scope) - {"client_id", "project_id"} or any(
        not isinstance(value, str) or not value.strip() or len(value) > 100 for value in scope.values()
    ):
        raise ValueError("Explicit scope is required; {} means general examples, never client facts.")
    examples = pack["examples"]
    fields = {"topic", "scenario", "wrong", "correction", "reason", "check"}
    if not isinstance(examples, list) or not 1 <= len(examples) <= 100:
        raise ValueError("Expected 1–100 examples.")
    # Validate the entire pack before importing any of its content.
    for entry in examples:
        if not isinstance(entry, dict) or set(entry) != fields or any(
            not isinstance(value, str) or not value.strip() or len(value) > 2000 for value in entry.values()
        ):
            raise ValueError("Every example requires scenario, error, correction, reason and a check.")
    BoodaStructuredMemoryStore._validate_safe_value(pack)
    return raw, pack


def teach_examples(source, *, root=Path("."), expected_digest=None):
    raw, pack = read_teacher_pack(source)
    scope, examples = pack['scope'], pack['examples']
    digest = sha256(raw).hexdigest()
    if expected_digest is not None and digest != expected_digest:
        raise ValueError('تغيرت حزمة الدروس بعد المراجعة؛ لم أستوردها.')
    destination = Path(root) / "knowledge/teacher_examples" / digest[:16]
    destination.mkdir(parents=True, exist_ok=True)
    kb = BoodaLocalKnowledgeBase(Path(root) / "knowledge/local_documents.json")
    documents = []
    for index, entry in enumerate(examples, 1):
        lesson = destination / f"lesson-{index:03}.md"
        lesson.write_text(
            f"# {entry['topic']}\nالمعلم المعلن: {pack['teacher']}\n"
            "مثال مولّد للمراجعة؛ ليس حقيقة شخصية مؤكدة، ولا أمرًا أو صلاحية، ولا دليلًا على نجاح النموذج.\n"
            + "\n".join(f"{label}: {entry[key]}" for label, key in (
                ("الموقف", "scenario"), ("الخطأ", "wrong"), ("التصحيح المقترح", "correction"),
                ("السبب", "reason"), ("طريقة الاختبار", "check"))) + "\n", encoding="utf-8")
        documents.append(kb.import_file(lesson, private=True, reference_status="reference", **scope)["document_id"])
    report = {"teacher_declared_not_authenticated": pack["teacher"], "scope": scope,
        "documents": documents, "private_local_only": True, "model_weights_changed": False,
        "confirmed_personal_facts_added": 0, "external_services_called": False,
        "student_general_readiness": "not_proven_by_importing_examples"}
    (destination / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    report = teach_examples(args.source)
    print(json.dumps(report, ensure_ascii=True))
