"""업로드 문서의 실제 형식·암호화·손상 검증을 테스트한다."""

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from pypdf import PdfWriter

from app.core.common.errors import AppValidationError, UnsupportedMediaTypeError
from app.domains.review_sessions import file_validation
from app.domains.review_sessions.file_validation import validate_document_content


def _pdf(*, encrypted: bool = False) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    if encrypted:
        writer.encrypt("secret")
    writer.write(output)
    return output.getvalue()


def _zip_document(**members: str | bytes) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for member, value in members.items():
            archive.writestr(member, value)
    return output.getvalue()


def _docx(*, document_xml: str = "<w:document xmlns:w='urn:word'/>") -> bytes:
    return _zip_document(
        **{
            "[Content_Types].xml": (
                "<Types xmlns='http://schemas.openxmlformats.org/"
                "package/2006/content-types'>"
                "<Override PartName='/word/document.xml' "
                "ContentType='application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document.main+xml'/>"
                "</Types>"
            ),
            "word/document.xml": document_xml,
        }
    )


def _hwpx(*, content_hpf: str = "<opf:package xmlns:opf='urn:opf'/>") -> bytes:
    return _zip_document(
        mimetype=b"application/hwp+zip",
        **{
            "version.xml": "<hcfVersion/>",
            "Contents/content.hpf": content_hpf,
            "Contents/section0.xml": "<hs:sec xmlns:hs='urn:section'/>",
        },
    )


def _hwp_v3(*, encrypted: bool = False, information_block_size: int = 0) -> bytes:
    signature = b"HWP Document File V3.00 \x1a\x01\x02\x03\x04\x05"
    document_info = bytearray(128)
    document_info[96:98] = int(encrypted).to_bytes(2, "little")
    document_info[124] = 0
    document_info[126:128] = information_block_size.to_bytes(2, "little")
    return signature + document_info + bytes(1008 + information_block_size)


@pytest.mark.parametrize(
    ("extension", "content"),
    [
        ("pdf", _pdf()),
        ("docx", _docx()),
        ("hwpx", _hwpx()),
        ("hwp", _hwp_v3()),
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
            _zip_document(
                **{
                    "[Content_Types].xml": "<Types/>",
                    "xl/workbook.xml": "<workbook/>",
                }
            ),
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


@pytest.mark.parametrize(
    ("extension", "content"),
    [
        ("docx", _docx(document_xml="not xml")),
        ("docx", _docx(document_xml="<workbook/>")),
        ("hwpx", _hwpx(content_hpf="not xml")),
        ("hwpx", _hwpx(content_hpf="<document/>")),
    ],
)
def test_malformed_xml_documents_are_rejected(
    extension: str,
    content: bytes,
) -> None:
    with pytest.raises(AppValidationError) as exc_info:
        validate_document_content(extension, content)

    assert exc_info.value.code == "CORRUPTED_FILE"


def test_zip_with_excessive_members_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(file_validation, "MAX_ZIP_MEMBER_COUNT", 1)

    with pytest.raises(AppValidationError) as exc_info:
        validate_document_content("docx", _docx())

    assert exc_info.value.code == "CORRUPTED_FILE"


def test_zip_with_excessive_uncompressed_size_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(file_validation, "MAX_ZIP_UNCOMPRESSED_SIZE", 10)

    with pytest.raises(AppValidationError) as exc_info:
        validate_document_content("docx", _docx())

    assert exc_info.value.code == "CORRUPTED_FILE"


def test_encrypted_hwp_v3_is_rejected() -> None:
    with pytest.raises(AppValidationError) as exc_info:
        validate_document_content("hwp", _hwp_v3(encrypted=True))

    assert exc_info.value.code == "ENCRYPTED_FILE"


def test_hwp_v3_information_block_must_fit_in_file() -> None:
    content = _hwp_v3(information_block_size=10)[:-1]

    with pytest.raises(AppValidationError) as exc_info:
        validate_document_content("hwp", content)

    assert exc_info.value.code == "CORRUPTED_FILE"


@pytest.mark.parametrize("extension", ["hwpml", "xls", "xlsx"])
def test_formats_outside_product_scope_are_rejected(extension: str) -> None:
    with pytest.raises(UnsupportedMediaTypeError) as exc_info:
        validate_document_content(extension, b"document")

    assert exc_info.value.code == "UNSUPPORTED_FILE_TYPE"
