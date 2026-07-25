"""업로드 문서의 실제 형식·암호화·손상 검증을 테스트한다."""

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from pypdf import PdfWriter

from app.common.errors import AppValidationError, UnsupportedMediaTypeError
from app.review_sessions.file_validation import validate_document_content


def _pdf(*, encrypted: bool = False) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    if encrypted:
        writer.encrypt("secret")
    writer.write(output)
    return output.getvalue()


def _zip_document(*members: str) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for member in members:
            archive.writestr(member, "<document/>")
    return output.getvalue()


@pytest.mark.parametrize(
    ("extension", "content"),
    [
        ("pdf", _pdf()),
        ("docx", _zip_document("[Content_Types].xml", "word/document.xml")),
        ("hwpx", _zip_document("Contents/content.hpf")),
        ("hwp", b"HWP Document File V3.00\x00body"),
    ],
)
def test_supported_document_structures_are_accepted(
    extension: str,
    content: bytes,
) -> None:
    validate_document_content(extension, content)


def test_encrypted_pdf_is_rejected() -> None:
    with pytest.raises(AppValidationError) as exc_info:
        validate_document_content("pdf", _pdf(encrypted=True))

    assert exc_info.value.code == "ENCRYPTED_FILE"


@pytest.mark.parametrize(
    ("extension", "content", "code"),
    [
        ("pdf", b"%PDF-1.4\nbroken", "CORRUPTED_FILE"),
        ("docx", b"not-a-zip", "FILE_TYPE_MISMATCH"),
        (
            "docx",
            _zip_document("[Content_Types].xml", "xl/workbook.xml"),
            "FILE_TYPE_MISMATCH",
        ),
        ("hwp", b"HWP Document File V3.00", "CORRUPTED_FILE"),
    ],
)
def test_mismatched_or_corrupted_documents_are_rejected(
    extension: str,
    content: bytes,
    code: str,
) -> None:
    expected_error = (
        UnsupportedMediaTypeError
        if code == "FILE_TYPE_MISMATCH"
        else AppValidationError
    )
    with pytest.raises(expected_error) as exc_info:
        validate_document_content(extension, content)

    assert exc_info.value.code == code


@pytest.mark.parametrize("extension", ["hwpml", "xls", "xlsx"])
def test_formats_outside_product_scope_are_rejected(extension: str) -> None:
    with pytest.raises(UnsupportedMediaTypeError) as exc_info:
        validate_document_content(extension, b"document")

    assert exc_info.value.code == "UNSUPPORTED_FILE_TYPE"
