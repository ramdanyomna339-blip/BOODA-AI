"""Deterministic offline planner for explicitly requested demo runs."""

from core.planning import BoodaPlan, PlanStep


class BoodaMockPlanner:
    """Create a clearly labeled, non-AI plan using only task-draft storage."""

    requires_explicit_permissions = True
    _CAPABILITY_NAME = "save_task_content"

    def __init__(self, *, permission_name):
        if not isinstance(permission_name, str) or not permission_name.strip():
            raise ValueError("Mock planning requires the save-task permission.")
        self.permission_name = permission_name
        self._configured = False

    def configure_agent(self, *, registry, permission_manager):
        if registry.get(self._CAPABILITY_NAME) is None:
            raise ValueError("The save_task_content capability is not available.")
        permissions = getattr(permission_manager, "permissions", None)
        if permissions is None or self.permission_name not in permissions:
            raise ValueError("Mock planning requires a registered save-task permission.")
        capability_registry = getattr(registry, "capability_registry", None)
        if capability_registry is not None:
            definition = capability_registry.get(self._CAPABILITY_NAME)
            if definition is None or not definition.enabled:
                raise ValueError("The save_task_content capability is not enabled.")
            if definition.permission_name != self.permission_name:
                raise ValueError("Mock planner permission does not match capability policy.")
        self._configured = True

    def create_plan(self, goal, memory):
        if not self._configured:
            raise RuntimeError("Configure the mock planner with BoodaAgent first.")
        safe_goal_id = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in goal.goal_id
        ).strip("_") or "goal"
        marker = "Demo / Mock — لا يوجد اتصال خارجي ولا توليد AI حقيقي."
        return BoodaPlan(
            goal_id=goal.goal_id,
            plan_id=f"demo-mock-{safe_goal_id}",
            steps=(
                PlanStep(
                    task_id=f"{safe_goal_id}-demo-mock-save-task-content",
                    title="Demo / Mock — مسودة توضيحية",
                    description=(
                        f"{marker}\n\n"
                        f"الهدف المطلوب: {goal.intent}\n\n"
                        "هذه مسودة ثابتة للتجربة فقط، وليست محتوى مولدًا أو إعلانًا منشورًا."
                    ),
                    capability=self._CAPABILITY_NAME,
                    permission_name=self.permission_name,
                    metadata={"provider": "mock", "demo": True},
                ),
            ),
        )

    def respond(self, message, *, context=None, memory=None):
        phase = (context or {}).get("phase", "غير محددة")
        return (
            "Demo / Mock — لا يوجد اتصال خارجي ولا توليد AI حقيقي. "
            f"حالة الهدف: {phase}."
        )
