"""Upload validation (US-2.1, ADR-014).

Type is determined by reading the file's own bytes, never by trusting the
filename extension or the client-supplied Content-Type. Both are attacker
controlled: `resume.pdf` can contain anything at all, and a browser will happily
send whatever Content-Type a crafted form specifies.

`python-magic` would do this too, but it needs the libmagic system library
installed in the image. The signatures we care about are two, so checking them
directly avoids a native dependency for nine lines of logic.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO

from app.core.exceptions import PayloadTooLargeError, UnsupportedMediaTypeError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB (US-2.1 AC2)

# A PDF must begin with %PDF- ... except that the spec tolerates leading junk,
# and real files produced by some tools have it. Scanning a small window rather
# than checking offset 0 accepts those without accepting arbitrary content.
_PDF_MAGIC = b"%PDF-"
_PDF_SEARCH_WINDOW = 1024

# DOCX is a ZIP container; every ZIP starts with this local file header.
_ZIP_MAGIC = b"PK\x03\x04"
# The entry that distinguishes an OOXML package from any other zip archive.
_OOXML_MARKER = "[Content_Types].xml"
_DOCX_DOCUMENT_ENTRY = "word/document.xml"


class DocumentType(StrEnum):
    PDF = "application/pdf"
    DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    content: bytes
    document_type: DocumentType
    size_bytes: int
    original_filename: str
    extension: str


def _looks_like_pdf(content: bytes) -> bool:
    return _PDF_MAGIC in content[:_PDF_SEARCH_WINDOW]


def _looks_like_docx(content: bytes) -> bool:
    """A zip that is specifically a Word document.

    Checking only the ZIP magic would accept any archive — including a zip bomb
    or a jar. Requiring the OOXML marker *and* word/document.xml means the file
    is a Word document rather than merely a zip that was renamed.
    """
    if not content.startswith(_ZIP_MAGIC):
        return False
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError):
        return False
    return _OOXML_MARKER in names and _DOCX_DOCUMENT_ENTRY in names


def detect_document_type(content: bytes) -> DocumentType | None:
    if _looks_like_pdf(content):
        return DocumentType.PDF
    if _looks_like_docx(content):
        return DocumentType.DOCX
    return None


def safe_extension(document_type: DocumentType) -> str:
    """Extension derived from detected type, not from the supplied filename."""
    return ".pdf" if document_type is DocumentType.PDF else ".docx"


def sanitize_filename(filename: str | None) -> str:
    """Reduce a client filename to something safe to store as metadata.

    Never used to build a storage path — that uses a generated UUID key
    (ADR-014). This exists so the original name can be displayed back to the
    user without carrying path traversal or control characters into logs and
    the UI.
    """
    if not filename:
        return "resume"

    # Take the basename under both separators: a Windows client sends
    # "C:\Users\me\resume.pdf", and splitting on "/" alone would keep all of it.
    base = filename.replace("\\", "/").split("/")[-1]

    cleaned = "".join(c for c in base if c.isprintable() and c not in '<>:"|?*\x00')
    cleaned = cleaned.strip(". ")

    return cleaned[:255] or "resume"


def validate_upload(*, content: bytes, filename: str | None) -> ValidatedUpload:
    """Validate an uploaded document, or raise.

    Runs before the request is accepted, so a bad file fails immediately with a
    precise status rather than being queued and failing invisibly in a worker
    (US-2.1).
    """
    size = len(content)

    if size == 0:
        raise UnsupportedMediaTypeError("The uploaded file is empty.")

    if size > MAX_UPLOAD_BYTES:
        raise PayloadTooLargeError(
            f"The file is {size / 1024 / 1024:.1f} MB. The maximum is "
            f"{MAX_UPLOAD_BYTES // 1024 // 1024} MB.",
            details={"size_bytes": size, "max_bytes": MAX_UPLOAD_BYTES},
        )

    document_type = detect_document_type(content)
    if document_type is None:
        # Deliberately does not echo the filename or any file content back.
        raise UnsupportedMediaTypeError(
            "Only PDF and DOCX resumes are supported. The file's contents did "
            "not match either format.",
            details={"accepted": ["application/pdf", "docx"]},
        )

    return ValidatedUpload(
        content=content,
        document_type=document_type,
        size_bytes=size,
        original_filename=sanitize_filename(filename),
        extension=safe_extension(document_type),
    )
