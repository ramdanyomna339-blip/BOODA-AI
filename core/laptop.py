"""Scoped local-device connection: system information and explicit text files.

No shell, background service, credentials, arbitrary process launch, deletion,
or global input injection is exposed by this first connection stage.
"""

import hashlib
import json
import os
from pathlib import Path
import platform
import re

from core.executor import BoodaExecutor
from core.permission_policy import BoodaPermissionPolicy
from core.risk import RiskLevel
from core.task import BoodaTask


LAPTOP_READ = "laptop_read"
LAPTOP_WRITE = "laptop_write"
TEXT_TYPES = {".txt", ".md", ".csv", ".json", ".py"}
WRITE_TYPES = {".txt", ".md", ".csv", ".json"}
BLOCKED_PARTS = {".git", ".ssh", ".aws", ".codex", ".agents", "security", "memory"}


class BoodaLaptopConnection:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir() or self.root.parent == self.root:
            raise ValueError("Select a specific existing working folder, not a drive root.")
        if any(p.casefold() in BLOCKED_PARTS for p in self.root.parts):
            raise ValueError("Sensitive system/state folders cannot be connection roots.")

    def _path(self, relative, *, directory=False, writing=False):
        if (not isinstance(relative, str) or len(relative) > 500 or "\\" in relative or ":" in relative
                or relative.startswith("/") or any(p in {"..", ""} for p in relative.split("/"))):
            raise ValueError("Use a relative path inside the connected folder.")
        for part in relative.split("/"):
            if relative == ".":
                continue
            if part.endswith((".", " ")) or part != part.strip() or re.fullmatch(
                    r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part, re.I):
                raise ValueError("Ambiguous or reserved Windows file paths are blocked.")
        raw = self.root / relative
        for part in raw.relative_to(self.root).parts:
            if (part.casefold() in BLOCKED_PARTS or part.startswith(".")
                    or re.search(r"(?:credential|password|secret|token|private.?key)", part, re.I)):
                raise ValueError("Sensitive file paths are blocked.")
        for ancestor in [raw, *raw.parents]:
            if ancestor == self.root:
                break
            if ancestor.is_symlink() or (hasattr(ancestor, "is_junction") and ancestor.is_junction()):
                raise ValueError("Linked folders/files are not accepted.")
        resolved = raw.resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError("Path escapes the connected folder.")
        if not directory and resolved.suffix.casefold() not in (WRITE_TYPES if writing else TEXT_TYPES):
            raise ValueError("Unsupported file type for this connection stage.")
        return resolved

    def task_for(self, operation, parameters=None):
        parameters = dict(parameters or {})
        if operation not in {"system_info", "list_files", "read_file", "write_file"}:
            raise ValueError("Unknown laptop operation.")
        canonical = json.dumps({"root": str(self.root), "operation": operation, "parameters": parameters},
                               ensure_ascii=True, sort_keys=True)
        task_id = "laptop-" + hashlib.sha256(canonical.encode()).hexdigest()
        return BoodaTask(task_id, f"Laptop: {operation}", metadata={"operation": operation, "parameters": parameters})

    def _perform(self, operation, parameters):
        if operation == "system_info":
            return {"os": platform.system(), "release": platform.release(),
                    "architecture": platform.machine(), "connected_root": str(self.root),
                    "ui_control": False, "shell_access": False}
        if operation == "list_files":
            path = self._path(parameters.get("path", "."), directory=True)
            if not path.is_dir():
                raise ValueError("Requested folder does not exist.")
            entries = []
            for item in sorted(path.iterdir()):
                try:
                    safe = self._path(item.relative_to(self.root).as_posix(), directory=item.is_dir())
                    entries.append({"path": safe.relative_to(self.root).as_posix(), "directory": item.is_dir()})
                except ValueError:
                    continue
                if len(entries) == 200:
                    break
            return {"entries": entries, "limit": 200}
        if operation == "read_file":
            path = self._path(parameters["path"])
            with path.open("rb") as source:
                raw = source.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ValueError("Connected text files are limited to 1 MB.")
            return {"path": path.relative_to(self.root).as_posix(), "text": raw.decode("utf-8-sig"),
                    "sha256": hashlib.sha256(raw).hexdigest()}
        if operation == "write_file":
            path = self._path(parameters["path"], writing=True)
            content = parameters["content"]
            if not isinstance(content, str) or len(content.encode("utf-8")) > 1_000_000:
                raise ValueError("Output must be UTF-8 text up to 1 MB.")
            if not path.parent.is_dir():
                raise ValueError("Choose an existing destination folder.")
            if path.suffix.casefold() == ".json":
                json.loads(content)
            # Exclusive creation avoids clobbering existing user data.
            with path.open("x", encoding="utf-8") as output:
                output.write(content)
            return {"path": str(path), "bytes": len(content.encode("utf-8")), "created": True}
        raise ValueError("Unknown laptop operation.")

    def execute(self, task, *, permission_manager, audit_log=None, approval=None):
        operation = task.metadata["operation"]
        parameters = task.metadata["parameters"]
        expected = self.task_for(operation, parameters)
        if task.task_id != expected.task_id:
            raise ValueError("Laptop request changed after review.")
        permission_name = LAPTOP_WRITE if operation == "write_file" else LAPTOP_READ
        if operation == "write_file":
            permission = permission_manager.get_permission(LAPTOP_WRITE)
            if permission is None or permission.risk_level not in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
                raise ValueError("Laptop writes require a high-risk permission and task-bound approval.")
        return BoodaExecutor().execute(task, lambda: self._perform(operation, parameters),
            permission_manager=permission_manager, permission_name=permission_name,
            permission_policy=BoodaPermissionPolicy(), approval=approval, audit_log=audit_log,
            requested_by="laptop_connection")

    def register_read_tools(self, registry, capability_registry=None):
        for name, operation in {"laptop_system_info": "system_info", "laptop_list_files": "list_files", "laptop_read_file": "read_file"}.items():
            if capability_registry is not None:
                definition = capability_registry.get(name)
                if definition is None:
                    capability_registry.register(name, description=f"Scoped laptop {operation}.",
                                                 permission_name=LAPTOP_READ, category="laptop")
                elif definition.permission_name != LAPTOP_READ:
                    raise ValueError("Laptop capability permission does not match the connection policy.")
            registry.register(name, lambda task, op=operation: self._perform(op, task.metadata))
