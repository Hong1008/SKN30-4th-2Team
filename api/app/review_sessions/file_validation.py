"""MCP 호출 전에 업로드 문서의 실제 컨테이너를 검증한다."""

from __future__ import annotations

import zipfile
from io import BytesIO

import olefile
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.common.errors import AppValidationError, UnsupportedMediaTypeError


OLE_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")
HWP_V3_SIGNATURE = b"HWP Document File V3.00"


def _invalid(code: str, message: str) -> AppValidationError:
    return AppValidationError(
        code=code,
        message=message,
        next_action="REUPLOAD",
    )


def _mismatch() -> UnsupportedMediaTypeError:
    return UnsupportedMediaTypeError(
        code="FILE_TYPE_MISMATCH",
        message="파일 확장자와 실제 형식이 일치하지 않습니다.",
        next_action="REUPLOAD",
    )


def _validate_pdf(content: bytes) -> None:
    if not content.startswith(b"%PDF-"):
        raise _mismatch()
    try:
        reader = PdfReader(BytesIO(content), strict=False)
        if reader.is_encrypted:
            raise _invalid("ENCRYPTED_FILE", "암호화된 파일은 업로드할 수 없습니다.")
        # 페이지 트리를 실제로 읽어 xref·trailer 손상을 조기에 발견한다.
        len(reader.pages)
    except AppValidationError:
        raise
    except (PdfReadError, ValueError, OSError) as error:
        raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.") from error


def _zip_members(content: bytes) -> set[str]:
    if not zipfile.is_zipfile(BytesIO(content)):
        if content.startswith(OLE_SIGNATURE):
            try:
                with olefile.OleFileIO(BytesIO(content)) as document:
                    if document.exists("EncryptedPackage"):
                        raise _invalid(
                            "ENCRYPTED_FILE",
                            "암호화된 파일은 업로드할 수 없습니다.",
                        )
            except AppValidationError:
                raise
            except (OSError, IOError):
                pass
        raise _mismatch()
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            infos = archive.infolist()
            if any(info.flag_bits & 0x1 for info in infos):
                raise _invalid(
                    "ENCRYPTED_FILE",
                    "암호화된 파일은 업로드할 수 없습니다.",
                )
            if archive.testzip() is not None:
                raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.")
            return {info.filename.replace("\\", "/") for info in infos}
    except AppValidationError:
        raise
    except (zipfile.BadZipFile, RuntimeError, OSError) as error:
        raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.") from error


def _validate_zip_document(extension: str, content: bytes) -> None:
    members = _zip_members(content)
    required_members = {
        "docx": {"[Content_Types].xml", "word/document.xml"},
        "hwpx": {"Contents/content.hpf"},
    }
    if not required_members[extension].issubset(members):
        raise _mismatch()


def _ole_stream_names(document: olefile.OleFileIO) -> set[str]:
    return {"/".join(parts) for parts in document.listdir()}


def _validate_hwp(content: bytes) -> None:
    if content.startswith(HWP_V3_SIGNATURE):
        if len(content) <= len(HWP_V3_SIGNATURE):
            raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.")
        return
    if not content.startswith(OLE_SIGNATURE):
        raise _mismatch()
    try:
        with olefile.OleFileIO(BytesIO(content)) as document:
            streams = _ole_stream_names(document)
            if {"EncryptionInfo", "EncryptedPackage"}.issubset(streams):
                raise _invalid(
                    "ENCRYPTED_FILE",
                    "암호화된 파일은 업로드할 수 없습니다.",
                )
            if "FileHeader" not in streams:
                raise _mismatch()
            header = document.openstream("FileHeader").read(40)
            if not header.startswith(b"HWP Document File"):
                raise _mismatch()
            if len(header) < 40:
                raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.")
            properties = int.from_bytes(header[36:40], "little")
            if properties & 0x2:
                raise _invalid(
                    "ENCRYPTED_FILE",
                    "암호화된 파일은 업로드할 수 없습니다.",
                )
    except (AppValidationError, UnsupportedMediaTypeError):
        raise
    except (OSError, IOError) as error:
        raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.") from error


def validate_document_content(extension: str, content: bytes) -> None:
    """확장자별 실제 문서 구조와 암호화·손상 여부를 검증한다."""
    if extension == "pdf":
        _validate_pdf(content)
    elif extension in {"docx", "hwpx"}:
        _validate_zip_document(extension, content)
    elif extension == "hwp":
        _validate_hwp(content)
    else:
        raise UnsupportedMediaTypeError(
            code="UNSUPPORTED_FILE_TYPE",
            message="지원하지 않는 파일 형식입니다.",
            next_action="REUPLOAD",
        )
