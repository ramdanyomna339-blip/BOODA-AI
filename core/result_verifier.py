"""Check observable artifact results, without claiming semantic correctness."""

from pathlib import Path

from core.file_action import _format_announcement


class BoodaArtifactVerifier:
    def __init__(self, registry_steps, task_manager, output_dir="outputs", *, knowledge_base=None):
        self.registry_steps = registry_steps
        self.task_manager = task_manager
        self.output_dir = Path(output_dir).resolve()
        self.knowledge_base = knowledge_base

    def verify(self, task, result, goal):
        steps = self.registry_steps()
        step = next((item for item in steps if item.task_id == task.task_id), None)
        if step is not None and step.capability == "search_local_knowledge" and self.knowledge_base is not None:
            return self._verify_sources(result, goal)
        if step is None or step.capability not in {
            "save_task_content", "create_plan_artifact",
        }:
            return None  # No verifier for this capability; never claim it passed.
        if not isinstance(result, (str, Path)):
            return False
        path = Path(result).resolve()
        if not path.is_relative_to(self.output_dir) or not path.is_file():
            return False
        if path.stat().st_size > 2 * 1024 * 1024:
            return False
        content = path.read_text(encoding="utf-8")
        criteria = goal.context.get("acceptance", {})
        if not isinstance(criteria, dict) or set(criteria) - {"required_text", "forbidden_text", "max_characters"}:
            raise ValueError("Unsupported user acceptance criteria.")
        for field in ("required_text", "forbidden_text"):
            values = criteria.get(field, [])
            if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
                raise ValueError("Acceptance text must be a list of nonempty strings.")
            if field == "required_text" and any(value not in content for value in values):
                return False
            if field == "forbidden_text" and any(value in content for value in values):
                return False
        maximum = criteria.get("max_characters")
        if maximum is not None:
            if type(maximum) is not int or maximum < 1:
                raise ValueError("Invalid maximum characters criterion.")
            if len(content) > maximum:
                return False
        if step.capability == "save_task_content":
            return content == _format_announcement(task.title, task.description)
        if f"معرّف الهدف: `{goal.goal_id}`" not in content:
            return False
        for item in steps:
            saved_task = self.task_manager.get_task(item.task_id)
            if saved_task is None or not all(value in content for value in (
                saved_task.title, saved_task.description,
                f"معرّف الخطوة: `{saved_task.task_id}`",
            )):
                return False
        return True

    def _verify_sources(self, result, goal):
        """Validate quoted evidence and scope, not factual truth or search completeness."""
        if not isinstance(result, dict) or result.get("private") is not True or not isinstance(result.get("sources"), list):
            return False
        if not result["sources"]:
            return None  # An empty search is not proof that information does not exist.
        for source in result["sources"]:
            if not isinstance(source, dict):
                return False
            document = self.knowledge_base.data["documents"].get(source.get("document_id"))
            if not document:
                return False
            for field in ("client_id", "project_id"):
                if document.get(field) is not None and document[field] != goal.context.get(field):
                    return False
                if source.get(field) != document.get(field):
                    return False
            chunk = next((item for item in document.get("chunks", [])
                          if item["chunk_id"] == source.get("chunk_id")), None)
            if chunk is None or source.get("text") != chunk["text"] or source.get("page") != chunk["page"]:
                return False
            for field in ("title", "source"):
                if source.get(field) != document[field]:
                    return False
            if source.get("reference_status") != document.get("reference_status", "reference"):
                return False
        return True
