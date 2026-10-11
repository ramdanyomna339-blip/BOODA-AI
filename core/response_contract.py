"""Explicit small output counts, enforced independently from model compliance."""
import re


def requested_format(message):
    if "جملتين فقط" in message:
        return "sentences", 2
    if "ثلاث نقاط فقط" in message or "ثلاثة نقاط فقط" in message:
        return "points", 3
    match = re.search(r"(?<!\d)([٢-٥2-5])\s+(جمل|نقاط)\s+فقط", message)
    return ("sentences" if match[2] == "جمل" else "points", int(match[1])) if match else None


def output_schema(contract):
    field, count = contract
    return {"type": "object", "properties": {field: {"type": "array", "minItems": count, "maxItems": count,
        "items": {"type": "string", "minLength": 1, "maxLength": 160}}},
        "required": [field], "additionalProperties": False}


def render_output(data, contract):
    field, count = contract
    if not isinstance(data, dict) or set(data) != {field}:
        raise ValueError("Model did not follow the requested response structure.")
    parts = data[field]
    if not isinstance(parts, list) or len(parts) != count or any(
        not isinstance(part, str) or not part.strip() or len(part) > 160 or "\n" in part for part in parts
    ):
        raise ValueError("Model did not follow the requested output count or length.")
    if field == "sentences":
        # Each array item must contain one sentence, never hide extra ones.
        if any(re.search(r"[.!?؟]\s+\S", part) for part in parts):
            raise ValueError("Model inserted extra sentences.")
        return " ".join(part.strip().rstrip(".؟?!") + "." for part in parts)
    return "\n".join(f"{index}. {part.strip()}" for index, part in enumerate(parts, 1))
