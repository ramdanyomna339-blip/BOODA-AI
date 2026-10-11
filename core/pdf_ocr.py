"""Bounded PDF page rasterization using the existing local Arabic OCR engine."""
from time import monotonic
from pathlib import Path
import subprocess
import sys
import json


def read_pdf_page(raw, index):
    try:
        result = subprocess.run([sys.executable, "-m", "core.pdf_ocr", str(index)],
                                input=raw, capture_output=True, timeout=60,
                                cwd=Path(__file__).resolve().parents[1])
    except subprocess.TimeoutExpired as error:
        raise ValueError("OCR page exceeded the time budget.") from error
    if result.returncode:
        raise ValueError("PDF OCR failed; check the local OCR dependencies and page limits.")
    return json.loads(result.stdout.decode("utf-8"))["text"]


def _read_pdf_page(raw, index):
    try:
        import pypdfium2 as pdfium
    except ImportError as error:
        raise ValueError("PDF OCR requires pypdfium2 and the local Arabic OCR setup.") from error
    from core.image_text import read_image_text
    started = monotonic()
    with pdfium.PdfDocument(raw) as document:
        if len(document) > 40:
            raise ValueError("OCR supports at most 40 PDF pages.")
        page = document[index]
        try:
            width, height = page.get_size()
            if width <= 0 or height <= 0:
                raise ValueError("Invalid PDF page size.")
            scale = min(2, (8_000_000 / (width * height)) ** .5)
            bitmap = page.render(scale=scale)
            try:
                image = bitmap.to_pil()
                try:
                    result = read_image_text(image)
                finally:
                    image.close()
            finally:
                bitmap.close()
        finally:
            page.close()
    if monotonic() - started > 60:
        raise ValueError("OCR page exceeded the time budget.")
    return result["text"]


if __name__ == "__main__":
    import site
    site.addsitedir(str(Path(__file__).resolve().parents[1] / ".desktop-deps"))
    raw = sys.stdin.buffer.read(20_000_001)
    if len(raw) > 20_000_000:
        raise ValueError("PDF too large")
    text = _read_pdf_page(raw, int(sys.argv[1]))
    sys.stdout.buffer.write(json.dumps({"text": text}, ensure_ascii=False).encode("utf-8"))
