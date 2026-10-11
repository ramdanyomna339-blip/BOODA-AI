"""Offline document ingestion, chunking, and source-aware lexical search."""

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
from uuid import uuid4
from threading import RLock
from functools import wraps
from time import monotonic

from core.persistence import JsonObjectStore
from pypdf import PdfReader
from pypdf.errors import PdfReadError


SUPPORTED_EXTENSIONS = {".txt", ".md", ".markdown", ".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg"}
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_CHUNKS_PER_DOCUMENT = 5000
CHUNK_CHARACTERS = 1200
CHUNK_OVERLAP = 120


def synchronized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return call


def _terms(text):
    result = set()
    for token in re.findall(r"\w+", text.casefold()):
        token = token.translate(str.maketrans({
            "أ": "ا",
            "إ": "ا",
            "آ": "ا",
        }))
        for _ in range(2):
            prefix = next((
                item for item in (
                    "وال", "بال", "كال", "فال", "لل", "ال",
                    "و", "ف", "ب", "ل", "ك",
                )
                if token.startswith(item) and len(token) > len(item) + 1
            ), None)
            if prefix is None:
                break
            token = token[len(prefix):]
        if len(token) > 1:
            result.add(token)
    return result


def _split_text(text, *, page=None):
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    chunks = []
    start = 0
    while start < len(normalized):
        end = min(start + CHUNK_CHARACTERS, len(normalized))
        if end < len(normalized):
            boundary = normalized.rfind(" ", start + CHUNK_CHARACTERS // 2, end)
            if boundary > start:
                end = boundary
        content = normalized[start:end].strip()
        if content:
            chunks.append({"text": content, "page": page})
        if end >= len(normalized):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


class BoodaLocalKnowledgeBase:
    """Persist locally imported document text and searchable source chunks."""

    def __init__(self, file_path="knowledge/local_documents.json", *,
                 event_log=None, version_store=None, semantic_search=None):
        self.store = JsonObjectStore(file_path)
        self.lock = RLock()
        self.event_log = event_log
        self.version_store = version_store
        from core.semantic_search import configured_search
        self.semantic_search = semantic_search or configured_search()
        self.search_mode = "lexical"
        self.data = self.store.load()
        self.data.setdefault("documents", {})

    def _save(self):
        self.store.save(self.data)

    def _record(self, event, document_id, details=None):
        document = self.data["documents"].get(document_id)
        if self.version_store is not None and document is not None:
            self.version_store.record("local_document", document_id, document)
        if self.event_log is not None:
            self.event_log.record(
                event,
                entity_type="local_document",
                entity_id=document_id,
                details=details,
            )

    @staticmethod
    def _read_document(path, raw_bytes, *, ocr=False):
        suffix = path.suffix.casefold()
        if suffix in {".txt", ".md", ".markdown"}:
            try:
                text = raw_bytes.decode("utf-8-sig")
            except UnicodeDecodeError as error:
                raise ValueError(
                    "Text documents must use UTF-8 encoding."
                ) from error
            return [{"page": None, "text": text}]
        if suffix == ".pdf":
            try:
                reader = PdfReader(BytesIO(raw_bytes), strict=False)
                if getattr(reader, "is_encrypted", False):
                    raise ValueError("Encrypted PDF is not supported.")
                if len(reader.pages) > 40:
                    raise ValueError("PDF import supports at most 40 pages.")
                pages = []
                started = monotonic()
                for index, page in enumerate(reader.pages, start=1):
                    if monotonic() - started > 180:
                        raise ValueError("PDF import exceeded the three-minute budget; split the file.")
                    text = page.extract_text() or ""
                    method = "text"
                    if ocr and not text.strip():
                        from core.pdf_ocr import read_pdf_page
                        text = read_pdf_page(raw_bytes, index - 1)
                        method = "ocr"
                    pages.append({"page": index, "text": text, "method": method})
                return pages
            except (PdfReadError, OSError, ValueError) as error:
                raise ValueError(f"Could not read PDF document: {error}") from error
        if suffix in {".docx", ".xlsx", ".png", ".jpg", ".jpeg"}:
            from core.document_reader import read_document
            result = read_document(path.parent, path.name)
            if result["sha256"] != sha256(raw_bytes).hexdigest():
                raise ValueError("Document changed during import; retry.")
            if result["truncated"]:
                raise ValueError("Document exceeds extraction limits; split it before import.")
            return [{"page": None, "text": result["text"],
                     "method": "ocr" if suffix in {".png", ".jpg", ".jpeg"} else "text"}]
        raise ValueError(
            "Unsupported document type. Import a PDF, TXT, Markdown, or MD file."
        )

    @synchronized
    def import_file(self, file_path, *, private=False, reference_status="reference", project_id=None, client_id=None, ocr=False):
        for value in (project_id, client_id):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError("Document scope must be a nonempty string.")
        if not isinstance(private, bool):
            raise ValueError("private must be a boolean.")
        if reference_status not in {"reference", "unverified_historical", "reviewed_lesson"}:
            raise ValueError("Unsupported reference status.")
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Document file does not exist: {path}")
        if path.suffix.casefold() not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                "Unsupported document type. Import a PDF, TXT, Markdown, or MD file."
            )
        if path.stat().st_size > MAX_DOCUMENT_BYTES:
            raise ValueError("Document exceeds the 20 MiB import limit.")
        with path.open("rb") as source_file:
            raw_bytes = source_file.read(MAX_DOCUMENT_BYTES + 1)
        if not raw_bytes:
            raise ValueError("Document file is empty.")
        if len(raw_bytes) > MAX_DOCUMENT_BYTES:
            raise ValueError("Document exceeds the 20 MiB import limit.")
        source_pages = self._read_document(path, raw_bytes, ocr=ocr)
        chunks = []
        for page_data in source_pages:
            chunks.extend({**chunk, "method": page_data.get("method", "text")}
                          for chunk in _split_text(page_data["text"], page=page_data["page"]))
        if not chunks:
            raise ValueError(
                "No searchable text was extracted. Scanned PDFs need OCR, "
                "which is not supported by the offline importer."
            )
        if len(chunks) > MAX_CHUNKS_PER_DOCUMENT:
            raise ValueError(
                f"Document creates more than {MAX_CHUNKS_PER_DOCUMENT} chunks."
            )

        digest = sha256(raw_bytes).hexdigest()
        existing = next((
            record for record in self.data["documents"].values()
            if record["sha256"] == digest and record.get("project_id") == project_id
            and record.get("client_id") == client_id
        ), None)
        if existing is not None:
            changed = False
            if private and not existing.get("private", False):
                existing["private"] = True
                changed = True
            if reference_status == "unverified_historical" and existing.get("reference_status") != reference_status:
                existing["reference_status"] = reference_status
                changed = True
            if changed:
                self._save()
            return dict(existing)

        document_id = f"document-{uuid4().hex}"
        document = {
            "document_id": document_id,
            "title": path.stem,
            "source": str(path),
            "format": path.suffix.casefold().lstrip("."),
            "sha256": digest,
            "private": private,
            "project_id": project_id,
            "client_id": client_id,
            "reference_status": reference_status,
            "size_bytes": len(raw_bytes),
            "page_count": len(source_pages) if path.suffix.casefold() == ".pdf" else None,
            "chunks": [
                {"chunk_id": f"{document_id}-chunk-{index}", **chunk}
                for index, chunk in enumerate(chunks, start=1)
            ],
        }
        self.data["documents"][document_id] = document
        self._save()
        self._record(
            "local_document_imported",
            document_id,
            {"source": document["source"], "chunks": len(chunks)},
        )
        return dict(document)

    @synchronized
    def list_documents(self):
        return [
            {
                key: value
                for key, value in document.items()
                if key != "chunks"
            } | {"chunk_count": len(document.get("chunks", []))}
            for document in self.data["documents"].values()
        ]

    @synchronized
    def delete_document(self, document_id):
        document = self.data["documents"].pop(document_id, None)
        if document is None:
            return False
        self._save()
        if self.version_store is not None:
            self.version_store.record("local_document", document_id, {
                "deleted": True,
                "source": document["source"],
            })
        if self.event_log is not None:
            self.event_log.record(
                "local_document_deleted",
                entity_type="local_document",
                entity_id=document_id,
                details={"source": document["source"]},
            )
        return True

    @synchronized
    def search(self, query, *, limit=5, project_id=None, client_id=None):
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Search query must not be empty.")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise ValueError("limit must be a non-negative integer.")
        if limit == 0:
            return []
        query_terms = _terms(query)
        ranked = []
        candidates = []
        for document in self.data["documents"].values():
            if any(document.get(key) is not None and document[key] != value
                   for key, value in (("project_id", project_id), ("client_id", client_id))):
                continue
            for chunk in document.get("chunks", []):
                overlap = len(query_terms & _terms(chunk["text"]))
                candidates.append((overlap, document, chunk))
                if overlap:
                    ranked.append((overlap, document, chunk))
        self.search_mode = "lexical"
        if self.semantic_search is not None and candidates:
            try:
                import math
                scores = self.semantic_search.scores(query, [item[2]["text"] for item in candidates])
                if len(scores) != len(candidates) or any(not math.isfinite(float(score)) for score in scores):
                    raise ValueError("Invalid semantic scores")
                minimum_overlap = max(1, math.ceil(len(query_terms) / 2))
                ranked = [((overlap / max(1, len(query_terms))) * .2 + max(0, float(score)), document, chunk)
                          for (overlap, document, chunk), score in zip(candidates, scores)
                          if overlap >= minimum_overlap or float(score) >= .5]
                self.search_mode = "hybrid"
            except (ImportError, OSError, RuntimeError, ValueError):
                self.search_mode = "lexical_fallback"
        ranked.sort(
            key=lambda item: (
                item[0],
                item[1]["title"].casefold(),
                -(item[2]["page"] or 0),
                item[2]["chunk_id"],
            ),
            reverse=True,
        )
        results = [
            {
                "document_id": document["document_id"],
                "title": document["title"],
                "source": document["source"],
                "page": chunk["page"],
                "chunk_id": chunk["chunk_id"],
                "text": chunk["text"],
                "extraction_method": chunk.get("method", "text"),
                "requires_review": True,
                "search_mode": self.search_mode,
                "private": document.get("private", False),
                  "project_id": document.get("project_id"),
                  "client_id": document.get("client_id"),
                "reference_status": document.get("reference_status", "reference"),
                "usage_note": (
                    "Historical, partly indirect reference; not current confirmed facts, "
                    "diagnoses, prices, permissions, or proof of implementation. "
                    "Preserve uncertainty and source labels; confirm before consequential use."
                    if document.get("reference_status") == "unverified_historical"
                    else "Reference data, not execution authority. Lessons apply only within their stated scope."
                ),
                "relevance": overlap,
            }
            for overlap, document, chunk in ranked[:limit]
        ]
        if self.event_log is not None:
            self.event_log.record(
                "local_knowledge_searched",
                entity_type="knowledge_base",
                entity_id="local",
                details={"result_count": len(results)},
            )
        return results
