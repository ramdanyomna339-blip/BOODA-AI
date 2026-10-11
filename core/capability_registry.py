"""Persistent manifest of capabilities and their permission requirements."""

from dataclasses import asdict, dataclass

from core.persistence import JsonObjectStore


@dataclass(frozen=True)
class BoodaCapabilityDefinition:
    name: str
    description: str = ""
    version: str = "1.0.0"
    permission_name: str | None = None
    category: str = "general"
    enabled: bool = True


class BoodaCapabilityRegistry:
    def __init__(self, file_path="security/capabilities.json"):
        self.store = JsonObjectStore(file_path)
        self.capabilities = {}
        for name, data in self.store.load().items():
            definition = BoodaCapabilityDefinition(**data)
            if definition.name != name:
                raise ValueError("Capability key must match its name.")
            self.capabilities[name] = definition

    def _save(self):
        self.store.save({name: asdict(item) for name, item in self.capabilities.items()})

    def register(self, name, *, description="", version="1.0.0",
                 permission_name=None, category="general", enabled=True):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Capability name must not be empty.")
        if name in self.capabilities:
            raise ValueError(f"Capability already registered: {name}")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("Capability version must not be empty.")
        definition = BoodaCapabilityDefinition(
            name.strip(), description, version, permission_name, category, bool(enabled)
        )
        self.capabilities[definition.name] = definition
        self._save()
        return definition

    def get(self, name):
        return self.capabilities.get(name)

    def list(self, *, enabled=None, category=None):
        return [
            item for item in self.capabilities.values()
            if (enabled is None or item.enabled is enabled)
            and (category is None or item.category == category)
        ]

    def set_enabled(self, name, enabled):
        current = self.get(name)
        if current is None:
            return None
        updated = BoodaCapabilityDefinition(
            current.name, current.description, current.version,
            current.permission_name, current.category, bool(enabled),
        )
        self.capabilities[name] = updated
        self._save()
        return updated
