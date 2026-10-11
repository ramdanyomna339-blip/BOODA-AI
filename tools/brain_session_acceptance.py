"""Exercise the real local application on a new client, then restart it."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from core.knowledge_base import BoodaLocalKnowledgeBase
from core.local_model import resolve_local_model_path


def run():
    project = Path(__file__).resolve().parents[1]
    folder = project / "outputs" / "brain_sessions" / uuid4().hex
    folder.mkdir(parents=True)
    source = folder / "client.txt"
    source.write_text("العميل سندس، رمز العقد عقد-903، موعد التسليم 2026-11-17.", encoding="utf-8")
    kb = BoodaLocalKnowledgeBase(folder / "knowledge/local_documents.json")
    kb.import_file(source, private=True, client_id="sundus", reference_status="unverified_historical")
    env = dict(os.environ, BOODA_AI_PROVIDER="local-tools", BOODA_CLIENT_ID="sundus",
               PYTHONPATH=str(project / ".desktop-deps") + os.pathsep
               + str(project / ".venv/Lib/site-packages") + os.pathsep + str(project))
    env.pop("BOODA_PROJECT_ID", None)
    report = {"scope": "real_application_local_model_disposable_client",
              "model_path": str(resolve_local_model_path()[1]), "runs": []}
    sequences = [
        "19\nابحث في المراجع المحلية عن رمز عقد العميل سندس ثم اعرض النتيجة\nنعم\nنعم\n"
        "اذكر رمز العقد فقط\n/تصحيح\nلون هوية سندس أحمر\nلون هوية سندس أزرق\nتأكيد العميل\nنعم\n"
        "/مهمة ابحث في المراجع المحلية عن موعد تسليم العميل سندس\nنعم\n/نفذ\n/حالة\n\n6\n",
        "19\n1\n/حالة\n/نفذ\n\n6\n",
    ]
    for index, sequence in enumerate(sequences, 1):
        print("Running actual application session " + str(index), flush=True)
        started = time.monotonic()
        result = subprocess.run([sys.executable, "-m", "tools.desktop_menu"], cwd=folder,
            env=env, input=sequence, encoding="utf-8", errors="replace", text=True,
            capture_output=True, timeout=210)
        (folder / f"session{index}.log").write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
        tasks = json.loads((folder / "memory/tasks.json").read_text(encoding="utf-8"))
        report["runs"].append({"returncode": result.returncode, "task_count": len(tasks),
            "seconds": round(time.monotonic() - started, 3),
            "completed": sum(item["status"] == "completed" for item in tasks.values()),
            "correct_contract_displayed": "عقد-903" in result.stdout,
            "correction_saved": "اتحفظ الدرس" in result.stdout,
            "resumed_without_execution": "لن تُعاد خطوات التنفيذ" in result.stdout,
            "verified_execution_report": "كل نتائج الخطوات اجتازت التحقق المسجل" in result.stdout,
            "stderr": result.stderr[-1000:]})
    first, reopened = report["runs"]
    report["passed"] = (first["returncode"] == reopened["returncode"] == 0
        and first["task_count"] == first["completed"] == reopened["task_count"] == reopened["completed"] == 2
        and first["correct_contract_displayed"] and first["correction_saved"]
        and reopened["resumed_without_execution"]
        and first["verified_execution_report"] and reopened["verified_execution_report"])
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("REPORT=" + str(folder / "report.json"), flush=True)
    if not report["passed"]:
        raise RuntimeError("Real application acceptance failed; inspect the saved session logs.")


if __name__ == "__main__":
    run()
