"""Constrain local JSON generation to registered tools and parameter shapes."""


def plan_schema(capability_permissions, *, min_steps=1, max_steps=12, review_observations=None):
    variants = []
    for name, permissions in capability_permissions.items():
        parameters = None
        if name in {"search_local_knowledge", "read_campaign_snapshot"}:
            key = "query" if name == "search_local_knowledge" else "snapshot_id"
            parameters = {"type": "object", "properties": {key: {"type": "string"}},
                          "required": [key], "additionalProperties": False}
        elif name == "review_output":
            dimensions = {"type": "array", "items": {"type": "integer", "minimum": 1},
                          "minItems": 2, "maxItems": 2}
            parameters = {"type": "object", "properties": {
                "required_dimensions": dict(dimensions, description="المقاس المطلوب: العرض والارتفاع"),
                "observed_dimensions": dict(dimensions, description="المقاس الملاحظ: العرض والارتفاع"),
                "required_text": {"type": "array", "items": {"type": "string"},
                                  "description": "النصوص المطلوبة حرفياً، أسماء ورموز؛ لا تضع المقاسات هنا"},
                "observed_text": {"type": "string", "description": "النص الملاحظ حرفياً، وليس المقاس"}},
                "required": ["required_dimensions", "observed_dimensions", "required_text", "observed_text"],
                "additionalProperties": False}
        metadata = {"type": "object"}
        if name == "review_output" and review_observations is not None:
            parameters = {"const": review_observations}
        if parameters is not None:
            metadata = {"type": "object", "properties": {"parameters": parameters},
                        "required": ["parameters"], "additionalProperties": False}
        dependencies = {"type": "array", "items": {"type": "string"}}
        if name in {"search_local_knowledge", "read_campaign_snapshot", "review_output"}:
            dependencies["maxItems"] = 0  # These tools accept complete literal inputs, not upstream bindings.
        variants.append({"type": "object", "properties": {
            "task_id": {"type": "string"}, "title": {"type": "string"},
            "description": {"type": "string"}, "capability": {"const": name},
            "permission_name": {"type": "string", "enum": list(permissions)},
            "depends_on": dependencies,
            "metadata": metadata, "due_at": {"type": "string"}},
            "required": ["task_id", "title", "description", "capability", "permission_name", "depends_on", "metadata"],
            "additionalProperties": False})
    return {"type": "object", "properties": {"plan_id": {"type": "string"},
        "steps": {"type": "array", "minItems": min_steps, "maxItems": max_steps,
                  "items": {"anyOf": variants}}}, "required": ["plan_id", "steps"],
        "additionalProperties": False}
