"""Small atomic JSON state storage shared by foundational managers."""

import json
import os
from pathlib import Path
import time
from uuid import uuid4


class JsonObjectStore:
    def __init__(self, file_path):
        self.file_path = Path(file_path)

    def load(self):
        if not self.file_path.exists():
            return {}
        with self.file_path.open("r", encoding="utf-8") as file:
            value = json.load(file)
        if not isinstance(value, dict):
            raise ValueError("State file must contain a JSON object.")
        return value

    def save(self, value):
        if not isinstance(value, dict):
            raise ValueError("State must be a JSON object.")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.file_path.with_name(self.file_path.name + "." + uuid4().hex + ".tmp")
        try:
            with temporary_path.open("x", encoding="utf-8") as file:
                json.dump(value, file, ensure_ascii=False, indent=2, default=str)
                file.flush()
                os.fsync(file.fileno())
            for attempt in range(5):
                try:
                    temporary_path.replace(self.file_path)
                    break
                except PermissionError as error:
                    if getattr(error, "winerror", None) not in {5, 32, 33} or attempt == 4:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        finally:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
