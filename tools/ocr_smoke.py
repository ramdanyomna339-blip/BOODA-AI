"""Exercise installed OCR on a generated fixture; does not read the desktop."""
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display
from core.image_text import read_image_text


def main():
    image = Image.new("RGB", (1400, 260), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 70)
    draw.text((1300, 20), get_display(arabic_reshaper.reshape("اختبار بودا")), font=font, fill="black", anchor="ra")
    draw.text((50, 140), "Booda 123", font=font, fill="black")
    result = read_image_text(image)
    result["passed"] = "بودا" in result["text"] and "123" in result["text"]
    output = Path("outputs/desktop_checks/ocr")
    output.mkdir(parents=True, exist_ok=True)
    image.save(output / "fixture.png")
    (output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
