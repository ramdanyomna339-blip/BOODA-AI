from core import screen_evidence


def test_ocr_evidence_stays_separate_and_bounded(monkeypatch):
    monkeypatch.setattr(screen_evidence, "read_image_text", lambda image:
        {"text": "ع" * 7000, "confidence": 81})
    result = screen_evidence.read_text_evidence(object())
    assert result["ocr_available"] and len(result["ocr_text"]) == 6000
    assert result["requires_review"] and result["ocr_confidence"] == 81
    assert "action" not in result


def test_missing_ocr_does_not_claim_reading(monkeypatch):
    def unavailable(image):
        raise RuntimeError("missing language data")
    monkeypatch.setattr(screen_evidence, "read_image_text", unavailable)
    result = screen_evidence.read_text_evidence(object())
    assert result["ocr_available"] is False and result["ocr_text"] == ""
