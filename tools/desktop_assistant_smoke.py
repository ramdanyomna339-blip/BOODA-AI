"""Real local reasoning using only the earlier synthetic image description."""
import json
from pathlib import Path
from core.desktop_assistant import BoodaDesktopAssistant
from core.local_model import ensure_local_model_server


def main():
    output = Path("outputs/desktop_checks")
    observation = json.loads((output / "vision.json").read_text(encoding="utf-8"))["description"]
    with ensure_local_model_server():
        try:
            result = BoodaDesktopAssistant().respond("اقترح فقط البحث على الويب عن تعليم الأشكال الظاهرة في الصورة. لا تنفذ أي شيء.", observation)
        except (ValueError, RuntimeError, OSError, KeyError, IndexError) as error:
            (output / "assistant.json").write_text(json.dumps({"passed": False, "executed": False, "error": str(error)}, ensure_ascii=False, indent=2), encoding="utf-8")
            raise
    if result["executed"] is not False or not result["action"] or result["action"]["operation"] != "search":
        raise RuntimeError("Expected a search proposal without execution.")
    output.mkdir(parents=True, exist_ok=True)
    result["passed"] = True
    (output / "assistant.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
