"""Keep OCR and vision evidence separate; neither can authorize an action."""
from core.image_text import read_image_text


def read_text_evidence(image):
    try:
        result = read_image_text(image)
        return {"ocr_text": result["text"][:6000], "ocr_confidence": result["confidence"],
                "ocr_available": True, "requires_review": True}
    except (ImportError, RuntimeError, OSError, ValueError):
        return {"ocr_text": "", "ocr_available": False, "requires_review": True}
