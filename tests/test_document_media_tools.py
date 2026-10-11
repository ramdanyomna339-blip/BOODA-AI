import io
import zipfile
import wave
import pytest
from core.document_reader import read_document, selected_file, check_zip
from core.public_media import download_public_media
from core.desktop_control import BoodaDesktopController, DESKTOP_PERMISSION
from core.permission_manager import BoodaPermissionManager


def test_word_arabic_and_read_only(tmp_path):
    path = tmp_path / "report.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>اختبار بودا</w:t></w:r></w:p></w:document>')
    before = path.read_bytes()
    result = read_document(tmp_path, "report.docx")
    assert "اختبار بودا" in result["text"] and result["untrusted"]
    assert path.read_bytes() == before


def test_excel_does_not_calculate_formulas(tmp_path):
    from openpyxl import Workbook
    book = Workbook()
    book.active.append(["العنوان", "=1+2"])
    book.save(tmp_path / "report.xlsx")
    result = read_document(tmp_path, "report.xlsx")
    assert "العنوان" in result["text"] and "=1+2" in result["text"]
    assert result["formulas_evaluated"] is False


def test_pdf_actual_text(tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 14 Tf 20 250 Td (Booda 123) Tj ET")
    page[NameObject("/Contents")] = content
    writer.write(tmp_path / "report.pdf")
    assert "Booda 123" in read_document(tmp_path, "report.pdf")["text"]


@pytest.mark.parametrize("path", ["../outside.txt", "secret.txt", "foo.exe", "C:/foo.txt", "missing.txt"])
def test_document_paths_guarded(tmp_path, path):
    with pytest.raises((ValueError, OSError)):
        selected_file(tmp_path, path)


def test_word_entities_rejected(tmp_path):
    with zipfile.ZipFile(tmp_path / "report.docx", "w") as archive:
        archive.writestr("word/document.xml", '<!DOCTYPE x [<!ENTITY leak SYSTEM "file:///C:/secrets">]><x>&leak;</x>')
    with pytest.raises(Exception):
        read_document(tmp_path, "report.docx")


def test_csv_bounded(tmp_path):
    (tmp_path / "table.csv").write_text("عنوان,قيمة\n" * 205, encoding="utf-8")
    result = read_document(tmp_path, "table.csv")
    assert result["truncated"] and len(result["text"].splitlines()) == 200


class Response:
    status = 200
    def __init__(self, data=b"sample", media="audio/mpeg", length=None):
        self.buffer = io.BytesIO(data)
        self.headers = {"Content-Type": media}
        if length is not None: self.headers["Content-Length"] = length
    def getheader(self, name, default=None): return self.headers.get(name, default)
    def read(self, limit): return self.buffer.read(limit)


class Connection:
    def __init__(self, response): self.response, self.closed = response, False
    def request(self, *args, **kwargs): self.requested = (args, kwargs)
    def getresponse(self): return self.response
    def close(self): self.closed = True


def fetch(tmp_path, response, **kwargs):
    connection = Connection(response)
    result = download_public_media("https://example.com/file", tmp_path,
        connection_factory=lambda host, address: connection,
        resolver=lambda *a, **k: [(None, None, None, None, ("8.8.8.8", 443))], **kwargs)
    assert connection.closed
    return result


def test_media_download_does_not_transcribe(tmp_path):
    from pathlib import Path
    result = fetch(tmp_path, Response())
    assert Path(result["path"]).read_bytes() == b"sample"
    assert result["transcribed"] is False


@pytest.mark.parametrize("response", [Response(b"123456", length="9"), Response(b"123456", length="999999999"), Response(media="text/html"), Response(b"")])
def test_incomplete_oversize_or_page_not_saved(tmp_path, response):
    with pytest.raises(ValueError): fetch(tmp_path, response)
    assert not list(tmp_path.iterdir())


def test_stream_over_limit_cleaned(tmp_path):
    with pytest.raises(ValueError): fetch(tmp_path, Response(b"123456"), max_bytes=5)
    assert not list(tmp_path.iterdir())


def test_private_media_not_connected(tmp_path):
    with pytest.raises(ValueError):
        download_public_media("https://example.com/file", tmp_path,
            resolver=lambda *a, **k: [(None, None, None, None, ("127.0.0.1", 443))],
            connection_factory=lambda *a: pytest.fail("must not connect"))


@pytest.mark.parametrize("operation", ["read_document", "download_media", "inspect_media"])
def test_added_operations_need_approval(operation):
    class Backend:
        def validate(self, *args): pass
        def target(self): return None
        def perform(self, *args): pytest.fail("must not execute")
    controller = BoodaDesktopController(Backend())
    task = controller.prepare(operation)
    permissions = BoodaPermissionManager()
    permissions.add_permission(DESKTOP_PERMISSION, allowed=True, risk_level="high")
    assert controller.execute(task, permission_manager=permissions) is None


def test_real_media_inspection_no_playback(tmp_path):
    from core.media_inspection import inspect_media
    path = tmp_path / "sample.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0\0" * 16000)
    result = inspect_media(path)
    assert result["duration_seconds"] == 1
    assert result["streams"][0]["type"] == "audio"
    assert not result["played"]


def test_disguised_remote_playlist_rejected(tmp_path):
    from core.media_inspection import inspect_media
    path = tmp_path / "playlist.mp4"
    path.write_text("#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\nhttps://example.com/segment.ts\n#EXT-X-ENDLIST\n")
    with pytest.raises(Exception):
        inspect_media(path)
