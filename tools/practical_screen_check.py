"""Evaluate an already-authorized real app frame, never capture another window."""
import json
import re
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / ".desktop-deps"))
    from PIL import Image
    from core.screen_observer import LocalScreenVision
    from core.vision_runtime import ensure_screen_vision
    output = root / "outputs/desktop_checks/practical"
    path = output / "calculator.png"
    if not path.is_file():
        raise ValueError("An authorized Calculator screenshot must be supplied first; this test does not capture the screen.")
    with Image.open(path) as image, ensure_screen_vision() as endpoint:
        vision = LocalScreenVision(endpoint=endpoint, timeout=150)
        generic = vision.describe(image)
        focused = vision.describe(image, question="Read only the large result on the calculator display at the top right, not the number buttons. Answer: The displayed result is NUMBER.")
    report = {"input": str(path), "source": "actual_calculator_frame_captured_earlier_this_turn_not_current_screen",
              "generic_description": generic, "focused_answer": focused, "expected_result": "4",
              "result_recognized": bool(re.search(r"\b4\b", focused)), "input_execution_tested": False,
              "native_booda_capture_tested": False}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    if not report["result_recognized"]:
        raise RuntimeError("Real calculator result was not recognized; inspect practical/report.json")


if __name__ == "__main__":
    main()
