"""Resolve narrow, explicit local read/review intents without model generation."""

from core.planning import BoodaPlan, PlanStep
from core.reasoning_checks import extract_review_observations


def direct_local_plan(goal, capabilities, permissions):
    text = goal.intent
    if any(name in text for name in capabilities):
        return None  # Keep explicitly named-tool generation separately testable.
    if any(word in text for word in ("انشر", "احذف", "اكتب", "احفظ", "أرسل", "ارسل", "اشتري", "ادفع")):
        return None  # Compound or consequential requests need the normal planner.
    name, parameters = None, None
    if "search_local_knowledge" in capabilities and any(
        phrase in text for phrase in ("ابحث في المراجع", "ابحث داخل المراجع", "ابحث في المعرفة المحلية")
    ):
        name, parameters = "search_local_knowledge", {"query": text[:500]}
    observations = extract_review_observations(text)
    if "review_output" in capabilities and observations is not None and "راجع" in text:
        name, parameters = "review_output", observations
    allowed = permissions.get(name, ()) if name else ()
    if len(allowed) != 1:
        return None
    title = "البحث في المراجع المحلية" if name == "search_local_knowledge" else "مراجعة المخرج حسب الملاحظات المعطاة"
    return BoodaPlan(goal.goal_id, (PlanStep(
        goal.goal_id + "-local-read", title, description=text,
        capability=name, permission_name=allowed[0], metadata={"parameters": parameters},
    ),), plan_id=goal.goal_id + "-local-read-plan")
