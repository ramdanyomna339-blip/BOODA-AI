"""Real local-model evaluations on disposable Arabic fixtures; no cloud calls."""

import json
import re
from pathlib import Path
import time
from uuid import uuid4

from core.brain import BoodaAgent
from core.capability_registry import BoodaCapabilityRegistry
from core.executor import BoodaExecutor
from core.knowledge_base import BoodaLocalKnowledgeBase
from core.llm_planner import OpenAICompatiblePlanner
from core.local_model import ensure_local_model_server, resolve_local_model_path
from core.permission_manager import BoodaPermissionManager
from core.permission_policy import BoodaPermissionPolicy
from core.planning import BoodaGoal
from core.reasoning_tools import register_reasoning_tools
from core.task_manager import BoodaTaskManager
from core.tool_registry import BoodaToolRegistry


def exact_fixture_retrieval(answer):
    """The fixture asks for two fields only; extra claims invalidate the score."""
    normalized = " ".join(answer.split())
    normalized = re.sub(r" المصدر: fixture \(تاريخي غير مؤكد\)$", "", normalized)
    return re.fullmatch(
        r"(?:رمز المشروع\s*[:：]\s*)?مرجع-742\s+(?:لون الهوية\s*[:：]\s*)?تركواز",
        normalized,
    ) is not None


def run(*, natural_tools=False):
    root = Path("outputs/brain_evaluations") / uuid4().hex
    root.mkdir(parents=True)
    report = {"scope": "real_local_model_disposable_fixtures", "cases": [],
              "natural_tools": natural_tools,
              "limits": "One run, 600-token schema-constrained plans / 160-token answers, 120-second deadline. No model weight changes. Heuristic scores require reading answers.",
              "production_permissions_changed": False}
    report["model_path"] = str(resolve_local_model_path()[1])
    report_path = root / "report.json"
    def save():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with ensure_local_model_server(startup_timeout=90) as endpoint:
        planner = OpenAICompatiblePlanner(base_url=endpoint, model="qwen3-local", timeout=120)
        send = planner._send_request
        report["raw_model_responses"] = []
        report["system_checks"] = "Literal field quotation, percentage conflicts, labeled Arabic review input parsing, direct planning of narrowly supported read/review intents, and review result wording use deterministic checks; they are not evidence of unaided model reasoning. Natural cases may need no model requests."
        def bounded(url, payload):
            is_plan = "response_format" in payload
            payload = dict(payload, max_tokens=600 if is_plan else 160,
                           chat_template_kwargs={"enable_thinking": False})
            response = send(url, payload)
            report["raw_model_responses"].append(response)
            return response
        planner.transport = bounded
        report["endpoint"] = endpoint
        report["model_alias"] = planner.model
        source = root / "fixture.md"
        source.write_text(
            "بيانات اختبار خيالية: العميل مرجان، رمز المشروع مرجع-742، لون الهوية تركواز.\n"
            "تعارض لم يُحسم: نسبة الإدارة 25% من ميزانية 7000، وملاحظة أخرى تقول أتعاب الإدارة 2250. "
            "لا نعرف سبب الفارق ولا الأتعاب الحالية.\n", encoding="utf-8")
        kb = BoodaLocalKnowledgeBase(root / "documents.json")
        kb.import_file(source, private=True, reference_status="unverified_historical")
        manifest = BoodaCapabilityRegistry(root / "capabilities.json")
        permissions = BoodaPermissionManager()
        registry = BoodaToolRegistry(manifest)
        mapping = register_reasoning_tools(registry, manifest, permissions,
                                          knowledge_base=kb, ad_intelligence=None)
        planner.capability_permissions = mapping
        planner.max_plan_steps = 3
        agent = BoodaAgent(planner, BoodaTaskManager(), registry, BoodaExecutor(),
                           knowledge_base=kb, permission_manager=permissions,
                           permission_policy=BoodaPermissionPolicy())
        agent.intake(BoodaGoal("fixture-goal", "راجع بيانات العميل مرجان"))

        def case(name, action, score):
            print("Running " + name, flush=True)
            started = time.monotonic()
            try:
                output = action()
                passed = score(output)
                item = {"name": name, "output": output, "heuristic_pass": passed,
                        "status": "heuristic_pass" if passed else "answer_requires_review"}
            except Exception as error:
                item = {"name": name, "error": type(error).__name__ + ": " + str(error),
                        "heuristic_pass": False, "status": "execution_error_not_reasoning_score"}
            item["seconds"] = round(time.monotonic() - started, 2)
            report["cases"].append(item)
            save()
            print(json.dumps({"case": name, "heuristic_pass": item["heuristic_pass"],
                              "seconds": item["seconds"]}), flush=True)

        case("retrieval", lambda: agent.respond("من مرجع العميل مرجان، اذكر رمز المشروع ولون الهوية فقط."),
             exact_fixture_retrieval)

        def tool_cycle():
            tool_request = ("ابحث في المراجع المحلية عن رمز مشروع مرجان ثم اعرض النتيجة. لا تخمن الرمز."
                            if natural_tools else "استخدم أداة search_local_knowledge للبحث عن رمز مشروع مرجان ثم اعرض النتيجة. لا تخمن الرمز.")
            agent.intake(BoodaGoal("tool-goal", tool_request),
                         replace_current=True)
            plan = agent.plan()
            agent.approve_plan(plan.plan_id)  # Explicitly authorized disposable read-only test.
            permissions.grant_permission("knowledge_read")
            outcomes = agent.run_until_blocked()
            result = agent.respond("ما رمز المشروع الذي وجدته في نتيجة البحث؟ اذكره فقط.")
            return {"plan": [{"capability": step.capability, "metadata": step.metadata} for step in plan.steps],
                    "task_statuses": [getattr(item, "status", None) for item in outcomes], "answer": result}
        case("tool_choice_and_result", tool_cycle,
             lambda output: "completed" in output["task_statuses"] and "742" in output["answer"]
             and len(output["plan"]) == 1 and output["task_statuses"] == ["completed"]
             and output["plan"][0]["capability"] == "search_local_knowledge")

        case("conflict_and_missing_information", lambda: agent.respond(
            "الأتعاب الحالية لمرجان كام؟ المرجع فيه 25% من 7000 وملاحظة 2250. هل تقدر تحسم؟ رد مختصر واذكر المعلومة الناقصة."),
             lambda answer: "1750" in answer and "2250" in answer
             and any(word in answer for word in ("تعارض", "تأكيد", "توضيح", "غير", "لا يمكن", "مش", "؟"))
             and "70%" not in answer)

        def review_cycle():
            review_request = "راجع المخرج: " if natural_tools else "راجع المخرج بأداة review_output: "
            agent.intake(BoodaGoal("review-goal", review_request + "المقاس المطلوب 1080×1080، "
                "المقاس الملاحظ 1920×1080. النصوص المطلوبة مرجان ومرجع-742. "
                "النص الملاحظ مرجان فقط. هل يصلح للتسليم؟ لا تعدله."), replace_current=True)
            plan = agent.plan()
            agent.approve_plan(plan.plan_id)
            permissions.grant_permission("output_review")
            outcomes = agent.run_until_blocked()
            return {"plan": [{"capability": step.capability, "metadata": step.metadata} for step in plan.steps],
                    "results": [getattr(item, "result", None) for item in outcomes],
                    "answer": agent.respond("اذكر عيوب المخرج بحسب نتيجة review_output فقط؛ هل جاهز؟")}
        case("output_review", review_cycle,
             lambda output: any(isinstance(item, dict) and item.get("ready") is False
                               and item.get("dimensions_match") is False
                               and "مرجع-742" in item.get("missing_text", []) for item in output["results"])
             and "742" in output["answer"] and "1080" in output["answer"])
    report["heuristic_passes"] = sum(item["heuristic_pass"] for item in report["cases"])
    report["completed_answers"] = sum("output" in item for item in report["cases"])
    save()
    print("REPORT=" + str(report_path.resolve()), flush=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--natural-tools", action="store_true")
    run(natural_tools=parser.parse_args().natural_tools)
