"""File intake checks (FILE-01) — run before any AI call.

Everything here is something the vendor can fix by uploading a different file, so problems become
VENDOR_ACTION findings with a specific instruction. File type is detected from the content
("magic bytes"), never trusted from the extension or browser-declared MIME type.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

from pypdf import PdfReader

logging.getLogger("pypdf").setLevel(logging.ERROR)  # damaged uploads are expected input, not log noise

MAX_BYTES = 10 * 1024 * 1024
# Abuse/cost guard, not a business rule: onboarding documents are 1–3 pages
# (a GST certificate with annexures is about 3).
MAX_PDF_PAGES = 10

SUPPORTED = "PDF, PNG or JPG"


@dataclass(frozen=True)
class FileInspection:
    mime: str | None  # detected type; None if unsupported
    problem: str | None  # vendor-facing reason the file can't be used; None if OK


def sniff_mime(data: bytes) -> str | None:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


def open_pdf(data: bytes) -> PdfReader:
    """Open a PDF, transparently handling 'encrypted' PDFs that have no user password
    (common for documents with print/copy restrictions — they open in any viewer)."""
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted and not reader.decrypt(""):
        raise PermissionError("password-protected")
    return reader


def inspect_file(data: bytes) -> FileInspection:
    if not data:
        return FileInspection(None, "the file is empty")
    if len(data) > MAX_BYTES:
        return FileInspection(None, f"the file is larger than {MAX_BYTES // (1024 * 1024)} MB")
    mime = sniff_mime(data)
    if mime is None:
        return FileInspection(None, f"this file type isn't supported — please upload a {SUPPORTED}")
    if mime == "application/pdf":
        try:
            pages = len(open_pdf(data).pages)
        except PermissionError:
            return FileInspection(mime, "the PDF is password-protected — please upload a copy without a password")
        except Exception:
            return FileInspection(mime, "the PDF is damaged and can't be opened")
        if pages == 0:
            return FileInspection(mime, "the PDF has no pages")
        if pages > MAX_PDF_PAGES:
            return FileInspection(mime, f"the PDF has {pages} pages — please upload only the relevant document")
    return FileInspection(mime, None)
