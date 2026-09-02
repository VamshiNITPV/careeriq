"""Tests for upload validation (US-2.1, ADR-014).

The theme: the filename and the client-supplied content type are never trusted.
Every decision comes from the bytes.
"""

from __future__ import annotations

import zipfile
from io import BytesIO

import pytest

from app.core.exceptions import PayloadTooLargeError, UnsupportedMediaTypeError
from app.services.file_validation import (
    MAX_UPLOAD_BYTES,
    DocumentType,
    detect_document_type,
    sanitize_filename,
    validate_upload,
)
from tests.fixtures.documents import build_docx, build_pdf


class TestTypeDetection:
    def test_detects_a_real_pdf(self) -> None:
        assert detect_document_type(build_pdf()) is DocumentType.PDF

    def test_detects_a_real_docx(self) -> None:
        assert detect_document_type(build_docx()) is DocumentType.DOCX

    def test_extension_alone_proves_nothing(self) -> None:
        """The core rule: a .pdf name on non-PDF bytes is not a PDF."""
        with pytest.raises(UnsupportedMediaTypeError):
            validate_upload(content=b"this is plain text, not a pdf" * 10, filename="resume.pdf")

    def test_rejects_an_executable_renamed_as_a_resume(self) -> None:
        # MZ header — a Windows executable. Accepting this because it was named
        # resume.docx is how a file store becomes a malware host.
        payload = b"MZ\x90\x00" + b"\x00" * 2048
        with pytest.raises(UnsupportedMediaTypeError):
            validate_upload(content=payload, filename="resume.docx")

    def test_rejects_a_plain_zip_pretending_to_be_docx(self) -> None:
        """A DOCX is a zip, but not every zip is a DOCX.

        Checking only the ZIP magic would accept any archive, including a zip
        bomb. The OOXML markers are what distinguish a Word document.
        """
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("hello.txt", "not a word document")

        with pytest.raises(UnsupportedMediaTypeError):
            validate_upload(content=buffer.getvalue(), filename="resume.docx")

    @pytest.mark.parametrize(
        "payload",
        [
            b"%PDF",  # truncated magic
            b"GIF89a" + b"\x00" * 200,
            b"\x89PNG\r\n\x1a\n" + b"\x00" * 200,
            b"<html><body>resume</body></html>" * 10,
        ],
    )
    def test_rejects_other_formats(self, payload: bytes) -> None:
        assert detect_document_type(payload) is None

    def test_accepts_a_pdf_with_leading_bytes(self) -> None:
        # The spec tolerates junk before the header, and some real producers
        # emit it. Scanning a small window accepts those without accepting
        # arbitrary content.
        assert detect_document_type(b"\n\n" + build_pdf()) is DocumentType.PDF


class TestSizeLimits:
    def test_rejects_an_empty_file(self) -> None:
        with pytest.raises(UnsupportedMediaTypeError):
            validate_upload(content=b"", filename="resume.pdf")

    def test_rejects_a_file_over_the_limit(self) -> None:
        oversized = b"%PDF-1.4" + b"\x00" * (MAX_UPLOAD_BYTES + 1)
        with pytest.raises(PayloadTooLargeError) as exc:
            validate_upload(content=oversized, filename="resume.pdf")
        assert exc.value.details["max_bytes"] == MAX_UPLOAD_BYTES

    def test_accepts_a_file_at_the_limit(self) -> None:
        # Off-by-one guard: exactly 5 MB must pass, not fail.
        padding = MAX_UPLOAD_BYTES - len(build_pdf())
        content = build_pdf() + b"\n%" + b" " * (padding - 2)
        result = validate_upload(content=content, filename="resume.pdf")
        assert result.size_bytes == MAX_UPLOAD_BYTES


class TestFilenameSanitization:
    @pytest.mark.parametrize(
        ("supplied", "expected"),
        [
            ("resume.pdf", "resume.pdf"),
            ("../../../etc/passwd", "passwd"),
            ("..\\..\\windows\\system32\\config", "config"),
            ("C:\\Users\\me\\Documents\\cv.docx", "cv.docx"),
            ("/absolute/path/cv.pdf", "cv.pdf"),
            ("", "resume"),
            (None, "resume"),
            ("...", "resume"),
        ],
    )
    def test_reduces_to_a_safe_basename(self, supplied: str | None, expected: str) -> None:
        assert sanitize_filename(supplied) == expected

    def test_strips_null_bytes_and_control_characters(self) -> None:
        # A NUL truncates a C string; a newline in a filename that later reaches
        # a Content-Disposition header is response splitting.
        assert "\x00" not in sanitize_filename("re\x00sume.pdf")
        assert "\n" not in sanitize_filename("resume\n.pdf")

    def test_caps_length(self) -> None:
        assert len(sanitize_filename("a" * 500 + ".pdf")) <= 255

    def test_keeps_unicode_names(self) -> None:
        # Rejecting non-ASCII names would exclude most of the world.
        assert sanitize_filename("résumé-प्रिया.pdf") == "résumé-प्रिया.pdf"


class TestValidatedUpload:
    def test_extension_comes_from_detected_type_not_the_filename(self) -> None:
        """A DOCX named .pdf must be stored as .docx.

        The storage key is built from this, so trusting the supplied extension
        would put mislabelled files in the store.
        """
        result = validate_upload(content=build_docx(), filename="resume.pdf")

        assert result.document_type is DocumentType.DOCX
        assert result.extension == ".docx"

    def test_returns_the_original_name_as_metadata_only(self) -> None:
        result = validate_upload(content=build_pdf(), filename="../../my cv.pdf")
        assert result.original_filename == "my cv.pdf"

    def test_reports_the_real_size(self) -> None:
        content = build_pdf()
        assert validate_upload(content=content, filename="cv.pdf").size_bytes == len(content)
