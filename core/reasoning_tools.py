"""Local read capabilities for the general planner; permissions remain explicit."""

from core.reasoning_checks import review_output

def register_reasoning_tools(registry, manifest, permissions, *, knowledge_base, ad_intelligence, scope_provider=None):
    def search(task):
        scope = scope_provider() if scope_provider is not None else {"project_id": task.project_id}
        return {"private": True, "sources": knowledge_base.search(_parameter(task, "query"), limit=5,
            project_id=scope.get("project_id"), client_id=scope.get("client_id"))}
    definitions = {
        "review_output": (
            "output_review", "Compare supplied output observations against requirements. metadata.parameters: "
            "{required_dimensions: [width,height], observed_dimensions: [width,height], "
            "required_text: [strings], observed_text: string}. This does not inspect images or modify output.",
            lambda task: review_output(task.metadata.get("parameters")),
        ),
        "search_local_knowledge": (
            "knowledge_read", "Search imported local documents. metadata.parameters: {query: string}.",
            search,
        ),
        "read_campaign_snapshot": (
            "campaign_read", "Read one saved campaign snapshot, not a live ad account. metadata.parameters: {snapshot_id: string}.",
            lambda task: _snapshot(ad_intelligence, _parameter(task, "snapshot_id")),
        ),
    }
    registered = {}
    for name, (permission, description, action) in definitions.items():
        if (name == "search_local_knowledge" and knowledge_base is None) or (
            name == "read_campaign_snapshot" and ad_intelligence is None
        ):
            continue
        definition = manifest.get(name)
        if definition is None:
            definition = manifest.register(name, permission_name=permission,
                                           description=description, category="local_read")
        if not definition.enabled:
            continue
        if definition.permission_name != permission:
            raise ValueError(f"Capability permission mismatch: {name}")
        if permissions.get_permission(permission) is None:
            permissions.add_permission(permission, allowed=False)
        registry.register(name, action)
        registered[name] = (permission,)
    return registered


def _parameter(task, name):
    parameters = task.metadata.get("parameters")
    # Accept only the exact unambiguous flat spelling emitted by small models.
    # Unknown fields and mixed flat/nested payloads remain rejected.
    if parameters is None and set(task.metadata) <= {name, "research_references"} and name in task.metadata:
        parameters = {name: task.metadata[name]}
    if not isinstance(parameters, dict) or set(parameters) != {name}:
        raise ValueError(f"Expected metadata.parameters with exactly {name}.")
    value = parameters[name]
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError(f"Invalid {name}.")
    return value.strip()


def _snapshot(manager, snapshot_id):
    record = manager.get_snapshot(snapshot_id)
    if record is None:
        raise ValueError("Saved campaign snapshot not found; no results were invented.")
    return {"private": True, "snapshot": record, "scope": "saved_snapshot_not_live_account"}
