"""Reviewed code changes, staged regression tests, guarded apply and rollback.

The staging directory isolates project files, NOT operating-system privileges.
Only code and tests explicitly reviewed by the user may run on the host.
"""

import ast
from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from uuid import uuid4

from core.executor import BoodaExecutor
from core.permission_policy import BoodaPermissionPolicy
from core.risk import RiskLevel
from core.task import BoodaTask


CODE_PERMISSION = "code_change"
DOCUMENT_GUARDS = {"document_reader", "public_media", "media_inspection", "youtube_captions", "video_sources", "arabic_console", "desktop_requests", "desktop_lessons", "screen_evidence"}
PROTECTED = {"executor", "approval", "approval_manager", "approval_store", "permission",
             "permission_manager", "permission_policy", "risk", "code_evolution", "laptop",
             "system_cli", "capability_registry", "tool_registry", "persistence",
             "desktop_control", "desktop_assistant", "desktop_workflow", "desktop_accessibility", "desktop_review", "model_workload", "screen_observer", "vision_runtime", "media_transcript", "browser_tools", "image_text", "tool_readiness"}


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class BoodaCodeEvolution:
    def __init__(self, root=".", *, database="memory/code_changes.sqlite3", lab="outputs/code_lab"):
        self.root = Path(root).resolve(strict=True)
        self.database = Path(database).resolve()
        self.lab = Path(lab).resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS changes (id TEXT PRIMARY KEY, status TEXT NOT NULL, payload TEXT NOT NULL)")

    def _db(self):
        return sqlite3.connect(self.database, timeout=30)

    def _target(self, relative):
        if not isinstance(relative, str) or not re.fullmatch(r"core/[a-zA-Z_][a-zA-Z0-9_]*\.py", relative):
            raise ValueError("Only an existing core Python module can be changed.")
        if Path(relative).stem in PROTECTED | DOCUMENT_GUARDS:
            raise ValueError("Permission, execution and connection guard modules cannot self-modify.")
        raw = self.root / relative
        if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in [raw, *raw.parents] if p != self.root.parent):
            raise ValueError("Symlink/reparse-point code paths are not accepted.")
        target = raw.resolve(strict=True)
        if not target.is_relative_to(self.root) or not target.is_file():
            raise ValueError("Code target is outside the project.")
        return target

    @staticmethod
    def _tree_hash(stage):
        rows = []
        for folder in ("core", "tests"):
            for path in sorted((stage / folder).rglob("*.py")):
                if "__pycache__" not in path.parts:
                    rows.append((str(path.relative_to(stage)), hashlib.sha256(path.read_bytes()).hexdigest()))
        return digest(json.dumps(rows))

    @staticmethod
    def _write(path, text):
        temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        try:
            for attempt in range(5):
                try:
                    temporary.replace(path)
                    return
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        finally:
            temporary.unlink(missing_ok=True)

    def get(self, change_id):
        with self._db() as db:
            row = db.execute("SELECT payload FROM changes WHERE id=?", (change_id,)).fetchone()
        if row is None:
            raise KeyError(change_id)
        return json.loads(row[0])

    def list_changes(self):
        with self._db() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM changes ORDER BY rowid DESC")]

    def _save(self, change, *, expected):
        with self._db() as db:
            result = db.execute("UPDATE changes SET status=?,payload=? WHERE id=? AND status=?",
                                (change["status"], json.dumps(change, ensure_ascii=False), change["id"], expected))
            if result.rowcount != 1:
                raise RuntimeError("Change state was modified by another operation.")

    def prepare(self, relative, proposed_text, *, test_files):
        target = self._target(relative)
        if not isinstance(proposed_text, str) or len(proposed_text.encode("utf-8")) > 200_000:
            raise ValueError("Proposed code exceeds the 200 KB limit.")
        ast.parse(proposed_text, filename=relative)
        if not isinstance(test_files, list) or not test_files:
            raise ValueError("At least one existing regression test file is required.")
        for name in test_files:
            if not isinstance(name, str) or not re.fullmatch(r"tests/test_[a-zA-Z0-9_]+\.py", name):
                raise ValueError("Test targets must be explicit tests/test_*.py paths.")
            test = (self.root / name).resolve(strict=True)
            if not test.is_relative_to(self.root) or not test.is_file():
                raise ValueError("Test target is outside the project.")
        original = target.read_text(encoding="utf-8")
        if original == proposed_text:
            raise ValueError("The proposal does not change code.")
        change_id = "code-" + uuid4().hex
        stage = self.lab / change_id
        stage.mkdir(parents=True, exist_ok=False)
        for folder in ("core", "tests"):
            for source in (self.root / folder).rglob("*.py"):
                if "__pycache__" in source.parts:
                    continue
                if (source.is_symlink() or source.stat().st_size > 1_000_000
                        or not source.resolve().is_relative_to(self.root)):
                    raise ValueError("Unsafe or oversized staged source.")
                destination = stage / source.relative_to(self.root)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
        (stage / relative).write_text(proposed_text, encoding="utf-8")
        change = {"id": change_id, "status": "prepared", "path": relative,
                  "original": original, "proposed": proposed_text,
                  "original_digest": digest(original), "proposed_digest": digest(proposed_text),
                  "stage_digest": self._tree_hash(stage), "test_files": test_files,
                  "apply_task_id": change_id + "-apply", "rollback_task_id": change_id + "-rollback",
                  "diff": "".join(difflib.unified_diff(original.splitlines(True), proposed_text.splitlines(True),
                                                        fromfile=relative, tofile=relative)),
                  "created_at": datetime.now(timezone.utc).isoformat(), "history": []}
        with self._db() as db:
            db.execute("INSERT INTO changes VALUES (?,?,?)", (change_id, change["status"], json.dumps(change)))
        return change

    def mark_reviewed(self, change_id, *, stage_digest):
        change = self.get(change_id)
        if change["status"] != "prepared" or stage_digest != change["stage_digest"]:
            raise ValueError("Review must bind the prepared source/test snapshot.")
        if self._tree_hash(self.lab / change_id) != stage_digest:
            raise ValueError("Staged source or tests changed after preparation.")
        change["status"] = "reviewed"
        change["history"].append({"action": "source_and_tests_reviewed", "digest": stage_digest})
        self._save(change, expected="prepared")

    def generate(self, relative, instruction, *, generator, test_files):
        if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 4000:
            raise ValueError("A specific improvement instruction is required.")
        original = self._target(relative).read_text(encoding="utf-8")
        # Validate and bound all test references before giving local model context.
        tests = {}
        for name in test_files[:5]:
            if not re.fullmatch(r"tests/test_[a-zA-Z0-9_]+\.py", name):
                raise ValueError("Invalid regression test path.")
            path = (self.root / name).resolve(strict=True)
            if not path.is_relative_to(self.root):
                raise ValueError("Test source is outside the project.")
            tests[name] = path.read_text(encoding="utf-8")[:10000]
        draft = generator.propose_code(path=relative, original=original, instruction=instruction, tests=tests)
        return self.prepare(relative, draft["code"], test_files=test_files)

    def validate(self, change_id, *, timeout=120):
        change = self.get(change_id)
        stage = self.lab / change_id
        if change["status"] != "reviewed" or self._tree_hash(stage) != change["stage_digest"]:
            raise ValueError("Review the complete staged source and tests before executing them.")
        if digest(self._target(change["path"]).read_text(encoding="utf-8")) != change["original_digest"]:
            raise ValueError("Live source changed since the proposal was prepared.")
        change["status"] = "testing"
        self._save(change, expected="reviewed")
        env = os.environ.copy()
        dependencies = [p for p in sys.path if p and "site-packages" in p]
        env.update(PYTHONPATH=os.pathsep.join([str(stage), *dependencies]),
                   PYTHONNOUSERSITE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
        try:
            completed = subprocess.run([sys.executable, "-m", "pytest", *change["test_files"], "-q",
                                        "--basetemp", str(stage / "test_tmp")], cwd=stage, env=env,
                                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
            passed = completed.returncode == 0 and self._tree_hash(stage) == change["stage_digest"]
            change["validation"] = {"returncode": completed.returncode,
                                    "output": (completed.stdout + completed.stderr)[-16000:],
                                    "passed": passed, "scope": "reviewed_host_process_not_os_sandbox"}
        except subprocess.TimeoutExpired:
            passed = False
            change["validation"] = {"passed": False, "output": "Regression test timeout."}
        except OSError as error:
            passed = False
            change["validation"] = {"passed": False, "output": type(error).__name__}
        change["status"] = "validated" if passed else "validation_failed"
        self._save(change, expected="testing")
        return self.get(change_id)

    def transition(self, change_id, *, rollback=False, permission_manager, approval, audit_log):
        change = self.get(change_id)
        expected = "applied" if rollback else "validated"
        if change["status"] != expected:
            raise ValueError("Change is not ready for this transition.")
        permission = permission_manager.get_permission(CODE_PERMISSION)
        if permission is None or permission.risk_level not in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
            raise ValueError("Code changes require a registered high-risk permission.")
        task_id = change["rollback_task_id"] if rollback else change["apply_task_id"]
        task = BoodaTask(task_id, "Rollback reviewed code" if rollback else "Apply tested code",
                         metadata={"change_id": change_id, "digest": change["proposed_digest"]})
        def action():
            target = self._target(change["path"])
            expected_digest = change["proposed_digest"] if rollback else change["original_digest"]
            if digest(target.read_text(encoding="utf-8")) != expected_digest:
                raise ValueError("Live code differs from the reviewed snapshot; refusing to overwrite it.")
            if not rollback and self._tree_hash(self.lab / change_id) != change["stage_digest"]:
                raise ValueError("Validated code or tests changed; refusing adoption.")
            change["status"] = "reverting" if rollback else "applying"
            self._save(change, expected=expected)
            try:
                self._write(target, change["original"] if rollback else change["proposed"])
                change["status"] = "reverted" if rollback else "applied"
                change["history"].append({"action": change["status"], "task_id": task_id})
                self._save(change, expected="reverting" if rollback else "applying")
                return {"change_id": change_id, "status": change["status"], "path": str(target)}
            except Exception:
                change["status"] = "uncertain"
                self._save(change, expected="reverting" if rollback else "applying")
                raise
        BoodaExecutor().execute(task, action, permission_manager=permission_manager,
                               permission_name=CODE_PERMISSION, permission_policy=BoodaPermissionPolicy(),
                               approval=approval, audit_log=audit_log, requested_by="code_evolution")
        return task
