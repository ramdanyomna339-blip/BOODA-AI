"""Reproducible checks on disposable fixtures, never on the application's code."""

import argparse
import ast
import json
from pathlib import Path
from uuid import uuid4

from core.approval_manager import BoodaApprovalManager
from core.audit_log import BoodaAuditLog
from core.code_evolution import BoodaCodeEvolution, CODE_PERMISSION, digest
from core.laptop import BoodaLaptopConnection, LAPTOP_READ, LAPTOP_WRITE
from core.permission_manager import BoodaPermissionManager


def run(*, local_model=False):
    run_root = Path("outputs/system_checks") / uuid4().hex
    run_root.mkdir(parents=True)
    report = {"scope": "disposable_fixture_tests", "live_project_code_changed": False}
    original, replacement = "def value():\n    return 1\n", "def value():\n    return 2\n"
    proposed = replacement
    if local_model:
        from core.local_model import ensure_local_model_server
        from core.semantic_research import BoodaSemanticAnalyzer
        print("Checking real local semantic analysis and code generation...", flush=True)
        with ensure_local_model_server() as endpoint:
            model = BoodaSemanticAnalyzer(base_url=endpoint)
            evidence = model.analyze("The campaign conversion rate increased.", [{"source_id": "S1", "text":
                "The campaign conversion rate decreased from 10 percent to 5 percent."}])
            report["semantic"] = {"evidence": evidence, "expected_contradiction_detected":
                                   any(e["relation"] == "contradicts" for e in evidence)}
            draft = model.propose_code(path="core/example.py", original=original,
                instruction="Change value() to return integer 2 instead of integer 1. Keep the file minimal.",
                tests={"tests/test_example.py": "def test_value(): assert value() == 2"})
            # Review the model draft against a known inert AST before executing it.
            safe = ast.dump(ast.parse(draft["code"])) == ast.dump(ast.parse(replacement))
            report["code_generation"] = {"draft": draft, "inert_fixture_ast_review_passed": safe}
            if not safe:
                raise ValueError("Generated code needs manual review; no generated code was executed.")
            proposed = draft["code"]
    print("Checking reviewed code regression, apply, and rollback...", flush=True)
    project = run_root / "project"
    (project / "core").mkdir(parents=True)
    (project / "tests").mkdir()
    (project / "core/__init__.py").write_text("", encoding="utf-8")
    (project / "core/example.py").write_text(original, encoding="utf-8")
    (project / "tests/test_example.py").write_text(
        "from core.example import value\ndef test_value():\n    assert value() == 2\n", encoding="utf-8")
    engine = BoodaCodeEvolution(project, database=run_root / "changes.sqlite3", lab=run_root / "lab")
    change = engine.prepare("core/example.py", proposed, test_files=["tests/test_example.py"])
    engine.mark_reviewed(change["id"], stage_digest=change["stage_digest"])
    validation = engine.validate(change["id"])
    if validation["status"] != "validated":
        raise RuntimeError(validation["validation"]["output"])
    permissions = BoodaPermissionManager()
    permissions.add_permission(CODE_PERMISSION, risk_level="high", allowed=True)
    permissions.add_permission(LAPTOP_READ, allowed=True)
    permissions.add_permission(LAPTOP_WRITE, risk_level="high", allowed=True)
    approvals = BoodaApprovalManager(file_path=run_root / "approvals.json")
    audit = BoodaAuditLog(run_root / "audit.jsonl")
    def approve(permission, task_id):
        key, item = approvals.create_approval(permission, "authorized_fixture_test", task_id=task_id)
        approvals.approve_approval(key)
        return item
    applied = engine.transition(change["id"], permission_manager=permissions,
        approval=approve(CODE_PERMISSION, change["apply_task_id"]), audit_log=audit)
    applied_text = (project / "core/example.py").read_text(encoding="utf-8")
    reverted = engine.transition(change["id"], rollback=True, permission_manager=permissions,
        approval=approve(CODE_PERMISSION, change["rollback_task_id"]), audit_log=audit)
    restored = (project / "core/example.py").read_text(encoding="utf-8")
    report["code_change"] = {"id": change["id"], "tests": validation["validation"],
        "apply_status": applied.status, "rollback_status": reverted.status,
        "patched_digest_matches": digest(applied_text) == digest(proposed), "original_restored": restored == original}
    if applied.status != "completed" or reverted.status != "completed" or restored != original:
        raise RuntimeError("Code apply/rollback check failed.")
    print("Checking actual scoped laptop file connection...", flush=True)
    folder = run_root / "laptop"
    folder.mkdir()
    connection = BoodaLaptopConnection(folder)
    note = "اختبار اتصال بودا باللابتوب: قراءة وكتابة داخل مجلد محدد."
    write = connection.task_for("write_file", {"path": "connection_test.txt", "content": note})
    connection.execute(write, permission_manager=permissions,
        approval=approve(LAPTOP_WRITE, write.task_id), audit_log=audit)
    read = connection.task_for("read_file", {"path": "connection_test.txt"})
    contents = connection.execute(read, permission_manager=permissions, audit_log=audit)
    info = connection.execute(connection.task_for("system_info"), permission_manager=permissions, audit_log=audit)
    try:
        connection._path("../outside.txt")
        escaped = True
    except ValueError:
        escaped = False
    report["laptop"] = {"system": info, "write_status": write.status, "read_status": read.status,
                        "roundtrip_matches": contents["text"] == note, "escape_blocked": not escaped}
    report["all_checks_passed"] = all([report["code_change"]["original_restored"],
        report["laptop"]["roundtrip_matches"], report["laptop"]["escape_blocked"],
        report.get("semantic", {}).get("expected_contradiction_detected", True)])
    destination = run_root / "report.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(destination.resolve(), flush=True)
    print("ALL CHECKS PASSED:", report["all_checks_passed"], flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-model", action="store_true")
    args = parser.parse_args()
    run(local_model=args.local_model)
