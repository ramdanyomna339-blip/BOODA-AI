import json

from core.context_builder import BoodaContextBuilder
from core.brain import BoodaAgent
from core.executor import BoodaExecutor
from core.planning import BoodaGoal
from core.planning import BoodaPlan, PlanStep
from core.task_manager import BoodaTaskManager
from core.tool_registry import BoodaToolRegistry
from core.user_profile import BoodaUserProfileManager


def test_context_builder_preserves_memory_and_applies_scoped_preferences(tmp_path):
    profiles = BoodaUserProfileManager(tmp_path / "profile.json")
    profiles.set_preference(
        "response_style",
        "مختصر وواضح",
        source="explicit",
        scope="project",
        scope_id="campaign-1",
    )
    profiles.set_preference(
        "learning_preferences",
        {"practice": "weekly"},
        source="explicit",
    )
    profiles.set_preference(
        "api_key",
        "must-not-enter-context",
        source="explicit",
    )
    builder = BoodaContextBuilder(profiles)

    context = builder.build(
        BoodaGoal("g1", "أتعلم", {"project_id": "campaign-1"}),
        {"goal_events": [{"event": "received"}], "learning_paths": []},
    )

    assert context["goal_events"] == [{"event": "received"}]
    assert context["learning_paths"] == []
    assert context["user_profile"]["language"] == "ar-EG"
    assert context["user_preferences"]["response_style"] == "مختصر وواضح"
    assert context["instructions"]["learning_preferences"] == {
        "practice": "weekly"
    }
    assert context["instructions"]["response_style"] == "مختصر وواضح"
    assert "api_key" not in json.dumps(context, ensure_ascii=False)
    assert context["instructions"]["priority"][0].startswith("قيود النظام")


def test_context_builder_wraps_non_dictionary_memory_without_losing_it(tmp_path):
    builder = BoodaContextBuilder(BoodaUserProfileManager(tmp_path / "profile.json"))

    context = builder.build(BoodaGoal("g", "تعلم"), ["previous", "entries"])

    assert context["prior_memory"] == ["previous", "entries"]
    assert context["instructions"]["language"] == "ar-EG"


def test_local_planner_receives_profile_context_as_structured_instructions(tmp_path):
    from core.llm_planner import OpenAICompatiblePlanner
    from core.local_model import BASE_URL, MODEL_NAME
    from core.permission_manager import BoodaPermissionManager
    from core.planning import BoodaGoal
    from core.tool_registry import BoodaToolRegistry

    captured = []
    response = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "plan_id": "plan-ar",
                    "steps": [
                        {
                            "task_id": f"task-{index}",
                            "title": f"خطوة {index}",
                    "description": [
                        "احصري ملفات المستخدم وحددي المجلدات المطلوب ترتيبها بوضوح.",
                        "صنفي الملفات حسب نوعها وتحققي من الأسماء المكررة قبل النقل.",
                        "رتبي الملفات في مجلدات مفهومة وسجلي أي عنصر يحتاج قرار المستخدم.",
                    ][index - 1],
                            "capability": "create_plan_artifact",
                            "depends_on": [],
                            "permission_name": "save_file",
                        }
                        for index in range(1, 4)
                    ],
                }, ensure_ascii=False),
            }
        }]
    }

    def transport(_endpoint, payload):
        captured.append(payload)
        return response

    planner = OpenAICompatiblePlanner(
        base_url=BASE_URL,
        model=MODEL_NAME,
        api_key=None,
        transport=transport,
        local_planning=True,
        min_plan_steps=3,
        max_plan_steps=7,
        capability_permissions={"create_plan_artifact": ("save_file",)},
    )
    registry = BoodaToolRegistry()
    registry.register("create_plan_artifact", lambda _task: "saved")
    permissions = BoodaPermissionManager()
    permissions.add_permission("save_file", allowed=True)
    planner.configure_agent(registry=registry, permission_manager=permissions)
    manager = BoodaUserProfileManager(tmp_path / "profile.json")
    context = BoodaContextBuilder(manager).build(
        BoodaGoal("g", "رتبي ملفي المحلي"),
        {"goal_events": []},
    )

    planner.create_plan(BoodaGoal("g", "رتبي ملفي المحلي"), context)

    user_message = captured[0]["messages"][1]["content"]
    assert '"language":"ar-EG"' in user_message
    assert "Egyptian colloquial Arabic" in user_message
    assert "avoid_unrequested_age_restriction_labels" in user_message
    assert "قيود السلامة والصلاحيات ومخطط JSON أولًا" in user_message


def test_agent_passes_built_profile_context_alongside_recalled_memory(tmp_path):
    profiles = BoodaUserProfileManager(tmp_path / "profile.json")
    profiles.update_profile(response_style="مصري بسيط")
    received = {}

    class Planner:
        def create_plan(self, goal, memory):
            received.update(memory)
            return BoodaPlan(
                goal.goal_id,
                (PlanStep("context-step", "Use the built context"),),
            )

    from core.memory import JsonlBoodaMemory

    agent = BoodaAgent(
        Planner(),
        BoodaTaskManager(),
        BoodaToolRegistry(),
        BoodaExecutor(),
        memory=JsonlBoodaMemory(tmp_path / "memory.jsonl"),
        context_builder=BoodaContextBuilder(profiles),
    )
    agent.intake(BoodaGoal("goal-context", "أتعلم", {"project_id": "project-1"}))
    agent.plan()

    assert received["goal_events"][0]["event"] == "goal_received"
    assert received["instructions"]["response_style"] == "مصري بسيط"
