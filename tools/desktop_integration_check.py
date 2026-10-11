"""Actual controllers/stores/requests, simulated native UI; public caption network."""
import json
from pathlib import Path
import uuid
from core.approval_manager import BoodaApprovalManager
from core.permission_manager import BoodaPermissionManager
from core.desktop_control import BoodaDesktopController, DESKTOP_PERMISSION
from core.desktop_requests import request_plan, excerpt_summary
from core.desktop_lessons import DesktopLessons
from core.youtube_captions import read_youtube_captions


class FixtureBackend:
    def __init__(self): self.text = ""
    def validate(self, operation, parameters): pass
    def target(self): return {"window": 1, "pid": 1, "title": "isolated fixture"}
    def perform(self, operation, p):
        if operation == "launch_app": self.text = ""
        elif operation == "type": self.text = p["text"]
        elif operation == "verify_text": return {"verified": p["expected"] == self.text}
        elif operation == "youtube_captions": return read_youtube_captions(p["url"], language=p["language"])
        elif operation == "excerpt_summary": return excerpt_summary(p["text"])
        return {"simulated": True}


def main():
    folder = Path("outputs/desktop_checks/integration") / uuid.uuid4().hex
    folder.mkdir(parents=True)
    permissions = BoodaPermissionManager()
    permissions.add_permission(DESKTOP_PERMISSION, allowed=True, risk_level="high")
    approvals = BoodaApprovalManager(file_path=folder / "approvals.json")
    report = {"native_input_tested": False, "human_result_check": "simulated",
              "runs": [], "passed": False}
    try:
        for request in ("اكتب في المفكرة: اختبار بودا", "افتح الفيديو ولخصه https://youtu.be/iG9CE55wbtY"):
            flow, controller = request_plan(request), BoodaDesktopController(FixtureBackend())
            statuses = []
            while flow.state == "ready":
                step = flow.next_step()
                task = controller.prepare(step["operation"], step["parameters"])
                flow.bind(task)
                key, approval = approvals.create_approval(DESKTOP_PERMISSION, "isolated-test", task_id=task.task_id)
                approvals.approve_approval(key)
                controller.execute(task, permission_manager=permissions, approval=approval)
                flow.record(task)
                statuses.append({"operation": step["operation"], "status": task.status})
                if flow.state == "awaiting_verification": flow.verify(True)
            report["runs"].append({"request": request, "state": flow.state, "steps": statuses})
            controller.stop()
        store = DesktopLessons(folder / "lessons.sqlite3")
        store.save("اكتب في المفكرة: اختبار", "تأكد من الصفحة الفارغة", user_confirmed=True)
        report["correction_recalled_after_reload"] = bool(DesktopLessons(folder / "lessons.sqlite3").recall("اكتب في المفكرة: اختبار"))
        report["passed"] = all(row["state"] == "completed" for row in report["runs"]) and report["correction_recalled_after_reload"]
    except Exception as error:
        report["error"] = str(error)
    path = folder / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "report": str(path.resolve())}, ensure_ascii=True))
    if not report["passed"]: raise SystemExit(1)


if __name__ == "__main__": main()
