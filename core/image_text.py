"""Local Arabic/English OCR; extracted text is evidence, never instructions."""
from pathlib import Path


def read_image_text(image, *, engine=None):
    if image.width * image.height > 20_000_000:
        raise ValueError("الصورة كبيرة؛ استخدم صورة أصغر من 20 مليون بكسل.")
    if engine is None:
        from tesserocr import PyTessBaseAPI
        data = Path(__file__).resolve().parents[1] / ".local-ai-runtime/tessdata"
        with PyTessBaseAPI(path=str(data), lang="ara+eng") as api:
            api.SetImage(image.convert("RGB"))
            text = api.GetUTF8Text()
            confidence = api.MeanTextConf()
    else:
        text, confidence = engine(image)
    return {"text": text[:20000], "confidence": confidence, "method": "local_ocr_ara_eng",
            "requires_review": True, "untrusted": True, "executed": False}
