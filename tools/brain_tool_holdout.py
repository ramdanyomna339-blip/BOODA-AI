"""New wording, real model plan, real local tool, independently checked source."""
import json
from pathlib import Path
import time
from uuid import uuid4

from core.brain import BoodaAgent
from core.capability_registry import BoodaCapabilityRegistry
from core.console import configure_utf8_console
from core.executor import BoodaExecutor
from core.knowledge_base import BoodaLocalKnowledgeBase
from core.llm_planner import OpenAICompatiblePlanner
from core.local_model import ensure_local_model_server, resolve_local_model_path
from core.permission_manager import BoodaPermissionManager
from core.permission_policy import BoodaPermissionPolicy
from core.planning import BoodaGoal
from core.reasoning_tools import register_reasoning_tools
from core.result_verifier import BoodaArtifactVerifier
from core.task_manager import BoodaTaskManager
from core.tool_registry import BoodaToolRegistry


def run():
    configure_utf8_console()
    folder = Path("outputs/brain_tool_holdouts") / uuid4().hex
    folder.mkdir(parents=True)
    document = folder / "contract.txt"
    document.write_text("العميل سلسبيل، رقم العقد عقد-816، موعد التسليم 2026-12-03.", encoding="utf-8")
    kb = BoodaLocalKnowledgeBase(folder / "kb.json")
    kb.import_file(document, private=True, client_id="salsabil")
    manifest = BoodaCapabilityRegistry(folder / "capabilities.json")
    permissions = BoodaPermissionManager()
    registry = BoodaToolRegistry(manifest)
    mapping = register_reasoning_tools(registry, manifest, permissions, knowledge_base=kb,
        ad_intelligence=None, scope_provider=lambda: {"client_id": "salsabil"})
    tasks = BoodaTaskManager()
    report = {"model_path": str(resolve_local_model_path()[1]), "scope": "real_model_unadapted_tool_wording",
              "model_calls": 0, "passed": False}
    with ensure_local_model_server(startup_timeout=90) as endpoint:
        planner = OpenAICompatiblePlanner(base_url=endpoint, model="qwen3-local", timeout=90,
            max_plan_steps=2, capability_permissions=mapping)
        original = planner.transport
        def transport(url, payload):
            report["model_calls"] += 1
            return original(url, payload)
        planner.transport = transport
        agent = BoodaAgent(planner, tasks, registry, BoodaExecutor(), permission_manager=permissions,
            permission_policy=BoodaPermissionPolicy(), knowledge_base=kb,
            verifier=BoodaArtifactVerifier(lambda: agent.state.plan.steps if agent.state.plan else (), tasks, knowledge_base=kb))
        started = time.monotonic()
        try:
            agent.intake(BoodaGoal("fresh-tool", "دوّر جوه المستندات المحفوظة على رقم عقد العميل سلسبيل، وورّيني الرقم بمصدره.", {"client_id": "salsabil"}))
            plan = agent.plan()
            report["plan"] = [{"capability": step.capability, "metadata": step.metadata} for step in plan.steps]
            agent.approve_plan(plan.plan_id)
            permissions.grant_permission("knowledge_read")
            agent.run_until_blocked()
            report["answer"] = agent.respond("اذكر رقم العقد فقط")
            report["passed"] = (report["model_calls"] >= 1 and len(plan.steps) == 1
                and plan.steps[0].capability == "search_local_knowledge"
                and tasks.get_task(plan.steps[0].task_id).status == "completed"
                and agent._verification_status(plan.steps[0].task_id) == "passed"
                and "عقد-816" in report["answer"])
        except Exception as error:
            report["error"] = type(error).__name__ + ": " + str(error)
        report["seconds"] = round(time.monotonic() - started, 2)
    destination = folder / "report.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("REPORT=" + str(destination.resolve()))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    run()
