"""Test installed vision using an invented picture, never the user's screen."""
import json
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / ".desktop-deps"))
    from PIL import Image, ImageDraw
    from core.screen_observer import LocalScreenVision
    image = Image.new("RGB", (640, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((70, 70, 250, 250), fill="red")
    draw.ellipse((350, 70, 530, 250), fill="blue")
    from core.vision_runtime import ensure_screen_vision
    with ensure_screen_vision() as endpoint:
        client = LocalScreenVision(endpoint=endpoint, timeout=180)
        description = client.describe(image)
    output = root / "outputs" / "desktop_checks"
    output.mkdir(parents=True, exist_ok=True)
    image.save(output / "synthetic.png")
    report = {"model": client.model, "description": description, "input": "synthetic_shapes_not_real_screen",
              "expected": "red square on left and blue circle on right", "requires_human_assessment": True}
    words = description.lower()
    report["known_shapes_recognized"] = all(word in words for word in ("red", "blue", "circle")) and ("square" in words or "rectangle" in words)
    report["background_recognized"] = "white" in words and "black background" not in words
    report["assessment"] = "basic_shapes_only_not_general_desktop_validation"
    (output / "vision.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if not report["known_shapes_recognized"]:
        raise RuntimeError("The model did not describe the known shapes; inspect vision.json before trusting it.")


if __name__ == "__main__":
    main()
