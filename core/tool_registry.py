from typing import Protocol


class BoodaCapability(Protocol):
    """A callable capability exposed to Booda through the tool registry."""

    def __call__(self, *args, **kwargs):
        ...


class BoodaToolRegistry:
    """Maps stable tool names to callable capabilities."""

    def __init__(self, capability_registry=None):
        self._tools = {}
        self.capability_registry = capability_registry

    def register(self, name, capability):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Tool name must be a non-empty string.")
        if not callable(capability):
            raise TypeError("Capability must be callable.")
        if self.capability_registry is not None:
            definition = self.capability_registry.get(name)
            if definition is None:
                raise ValueError(f"Capability is not registered: {name}")
            if not definition.enabled:
                raise ValueError(f"Capability is disabled: {name}")
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        self._tools[name] = capability
        return capability

    def get(self, name):
        if self.capability_registry is not None:
            definition = self.capability_registry.get(name)
            if definition is None or not definition.enabled:
                return None
        return self._tools.get(name)

    def require(self, name):
        capability = self.get(name)
        if capability is None:
            raise KeyError(f"Tool not found: {name}")
        return capability

    def names(self):
        return tuple(self._tools)
