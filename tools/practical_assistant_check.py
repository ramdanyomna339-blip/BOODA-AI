"""Test local reasoning on the already-approved Calculator observation, without UI input."""
import json
from pathlib import Path

from core.desktop_assistant import BoodaDesktopAssistant
from core.local_model import ensure_local_model_server


def main():
    output = Path(__file__).resolve().parents[1] / "outputs/desktop_checks/practical"
    source = json.loads((output / "report.json").read_text(encoding="utf-8"))
    report = {"source": "previous_authorized_calculator_observation_not_current_screen",
              "screen_captured": False, "input_executed": False, "passed": False}
    try:
        with ensure_local_model_server():
            result = BoodaDesktopAssistant().respond(
                "ما الرقم الظاهر في شاشة الحاسبة؟ أجب فقط دون اقتراح أي إجراء.",
                source["focused_answer"])
        report["assistant"] = result
        report["passed"] = (result["action"] is None and result["executed"] is False
                            and any(number in result["answer"] for number in ("4", "٤", "أربعة", "اربعة")))
    except (ValueError, RuntimeError, OSError, KeyError, IndexError) as error:
        report["error"] = str(error)
    (output / "assistant.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    if not report["passed"]:
        raise RuntimeError("Calculator reasoning did not pass; inspect practical/assistant.json")


if __name__ == "__main__":
    main()
