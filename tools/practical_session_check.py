"""Replay an authorized app frame through the actual observation/question pipeline."""
import json
import sys
import time
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / ".desktop-deps"))
    from PIL import Image
    from core.screen_observer import LocalScreenVision, ScreenObservationSession
    from core.vision_runtime import ensure_screen_vision
    output = root / "outputs/desktop_checks/practical"
    report = {"source": "replay_of_previous_authorized_calculator_frame",
              "live_capture_tested": False, "input_execution_tested": False, "passed": False}
    try:
        started = time.monotonic()
        with Image.open(output / "calculator.png") as image, ensure_screen_vision() as endpoint:
            session = ScreenObservationSession(image.copy, LocalScreenVision(endpoint=endpoint, timeout=150), duration=600)
            session.ask("What is the large result displayed at the top right of the calculator? Answer in Arabic. Do not propose any action.")
            result = session.step()
            if result is not None:
                reply = result["assistant_reply"]
                report.update(description=result["description"], assistant=reply,
                              frames_analyzed=result["sequence"])
                report["passed"] = (reply is not None and reply["action"] is None
                    and reply["executed"] is False and any(number in reply["answer"] for number in ("4", "٤", "أربعة", "اربعة")))
            session.stop()
            report["stopped"] = session.stopped.is_set() and session.latest is None
            report["elapsed_seconds"] = round(time.monotonic() - started, 2)
    except (ValueError, RuntimeError, OSError, KeyError, IndexError) as error:
        report["error"] = str(error)
    (output / "session.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    if not report["passed"]:
        raise RuntimeError("Observation pipeline replay failed; inspect practical/session.json")


if __name__ == "__main__":
    main()
