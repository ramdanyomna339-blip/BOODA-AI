import pytest

from core.tool_registry import BoodaToolRegistry


def test_registry_registers_and_resolves_callable_capability():
    registry = BoodaToolRegistry()
    capability = lambda value: value.upper()

    registered = registry.register("text.transform", capability)

    assert registered is capability
    assert registry.get("text.transform") is capability
    assert registry.require("text.transform")("hello") == "HELLO"
    assert registry.names() == ("text.transform",)


def test_registry_rejects_duplicate_names():
    registry = BoodaToolRegistry()
    registry.register("text.transform", lambda: None)

    with pytest.raises(ValueError, match="already registered"):
        registry.register("text.transform", lambda: None)


def test_registry_rejects_invalid_entries():
    registry = BoodaToolRegistry()

    with pytest.raises(ValueError, match="non-empty"):
        registry.register(" ", lambda: None)
    with pytest.raises(TypeError, match="callable"):
        registry.register("text.transform", object())


def test_registry_reports_missing_tool():
    registry = BoodaToolRegistry()

    assert registry.get("unknown") is None
    with pytest.raises(KeyError, match="Tool not found"):
        registry.require("unknown")
