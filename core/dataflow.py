"""Resolve declared read-only inputs from verified dependency results."""

from copy import deepcopy


def validate_bindings(step):
    bindings = step.metadata.get("input_bindings", {})
    if not isinstance(bindings, dict) or len(bindings) > 8:
        raise ValueError("Invalid input bindings.")
    allowed = {"search_local_knowledge": {"query"}, "review_output": {"observed_text"}}
    for parameter, binding in bindings.items():
        if parameter not in allowed.get(step.capability, set()):
            raise ValueError("Result bindings are limited to read-only observation inputs.")
        if not isinstance(binding, dict) or set(binding) != {"task_id", "path"}:
            raise ValueError("Binding requires a dependency id and result path.")
        if binding["task_id"] not in step.depends_on:
            raise ValueError("Binding source must be a direct dependency.")
        path = binding["path"]
        if not isinstance(path, list) or not 1 <= len(path) <= 8 or any(
            not (isinstance(key, str) and key and not key.startswith("_"))
            and not (type(key) is int and 0 <= key <= 1000) for key in path
        ):
            raise ValueError("Invalid result path.")


def resolve_bindings(step, tasks, verification_status):
    validate_bindings(step)
    metadata = deepcopy(step.metadata)
    for parameter, binding in metadata.get("input_bindings", {}).items():
        source = tasks[binding["task_id"]]
        if source.status != "completed" or verification_status(source.task_id) != "passed":
            raise ValueError("A result binding requires a successfully verified dependency.")
        value = source.result
        try:
            for key in binding["path"]:
                if isinstance(value, dict) and isinstance(key, str): value = value[key]
                elif isinstance(value, list) and type(key) is int: value = value[key]
                else: raise ValueError("Result path does not match the evidence.")
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError("Required evidence is missing; no input was invented.") from error
        if not isinstance(value, str) or not value.strip() or len(value) > 20000:
            raise ValueError("Read-only input must be bounded nonempty text.")
        parameters = metadata.setdefault("parameters", {})
        if not isinstance(parameters, dict):
            raise ValueError("Parameters must be an object.")
        parameters[parameter] = value
    return metadata
