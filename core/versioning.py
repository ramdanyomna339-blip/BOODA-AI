"""Append-only snapshots for tracking changes to foundational entities."""

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class BoodaVersionStore:
    def __init__(self, file_path="memory/versions.jsonl"):
        self.file_path = Path(file_path)

    def record(self, entity_type, entity_id, snapshot, *, changed_by=None, reason=None):
        if not entity_type or not entity_id:
            raise ValueError("Version records require an entity type and id.")
        versions = self.history(entity_type, entity_id)
        entry = {
            "version_id": f"version-{uuid4().hex}",
            "entity_type": entity_type,
            "entity_id": entity_id,
            "version": len(versions) + 1,
            "snapshot": snapshot,
            "changed_by": changed_by,
            "reason": reason,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        with self.file_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        return entry

    def history(self, entity_type, entity_id):
        if not self.file_path.exists():
            return []
        result = []
        with self.file_path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry["entity_type"] == entity_type and entry["entity_id"] == entity_id:
                    result.append(entry)
        return result
