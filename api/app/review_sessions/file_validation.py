"""MCP 호출 전에 업로드 문서의 실제 컨테이너를 검증한다."""

from __future__ import annotations

import zipfile
from io import BytesIO
from xml.etree import ElementTree

import olefile
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.common.errors import AppValidationError, UnsupportedMediaTypeError


OLE_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")
HWP_V3_PREFIX = b"HWP Document File V3.00"
HWP_V3_SIGNATURE = HWP_V3_PREFIX + b" \x1a\x01\x02\x03\x04\x05"
HWP_V3_FIXED_SIZE = len(HWP_V3_SIGNATURE) + 128 + 1008
MAX_ZIP_MEMBER_COUNT = 2048
MAX_ZIP_UNCOMPRESSED_SIZE = 100 * 1024 * 1024
MAX_XML_SIZE = 16 * 1024 * 1024


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


def _validate_zip_infos(infos: list[zipfile.ZipInfo]) -> set[str]:
    if len(infos) > MAX_ZIP_MEMBER_COUNT:
        raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.")
    total_size = 0
    members: set[str] = set()
    for info in infos:
        name = info.filename.replace("\\", "/")
        if name in members:
            raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.")
        members.add(name)
        total_size += info.file_size
        if (
            info.file_size < 0
            or info.compress_size < 0
            or total_size > MAX_ZIP_UNCOMPRESSED_SIZE
        ):
            raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.")
    return members


def _read_xml(archive: zipfile.ZipFile, member: str) -> ElementTree.Element:
    info = archive.getinfo(member)
    if info.file_size > MAX_XML_SIZE:
        raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.")
    raw = archive.read(info)
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.")
    try:
        return ElementTree.fromstring(raw)
    except ElementTree.ParseError as error:
        raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.") from error


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _validate_docx(archive: zipfile.ZipFile, members: set[str]) -> None:
    required = {"[Content_Types].xml", "word/document.xml"}
    if not required.issubset(members):
        raise _mismatch()

    content_types = _read_xml(archive, "[Content_Types].xml")
    document = _read_xml(archive, "word/document.xml")
    if _local_name(content_types.tag) != "Types":
        raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.")
    if _local_name(document.tag) != "document":
        raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.")

    main_document_declared = any(
        _local_name(element.tag) == "Override"
        and element.attrib.get("PartName") == "/word/document.xml"
        and element.attrib.get("ContentType")
        in {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
            "application/vnd.ms-word.document.macroEnabled.main+xml",
        }
        for element in content_types
    )
    if not main_document_declared:
        raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.")


def _validate_hwpx(archive: zipfile.ZipFile, members: set[str]) -> None:
    required = {
        "mimetype",
        "version.xml",
        "Contents/content.hpf",
        "Contents/section0.xml",
    }
    if not required.issubset(members):
        raise _mismatch()
    if archive.read("mimetype") != b"application/hwp+zip":
        raise _mismatch()

    version = _read_xml(archive, "version.xml")
    package = _read_xml(archive, "Contents/content.hpf")
    section = _read_xml(archive, "Contents/section0.xml")
    if _local_name(version.tag).lower() not in {"hcfversion", "version"}:
        raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.")
    if _local_name(package.tag) != "package":
        raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.")
    if _local_name(section.tag) not in {"sec", "section"}:
        raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.")


def _validate_zip_document(extension: str, content: bytes) -> None:
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
            members = _validate_zip_infos(infos)
            if archive.testzip() is not None:
                raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.")
            if extension == "docx":
                _validate_docx(archive, members)
            else:
                _validate_hwpx(archive, members)
    except AppValidationError:
        raise
    except UnsupportedMediaTypeError:
        raise
    except (KeyError, zipfile.BadZipFile, RuntimeError, OSError) as error:
        raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.") from error


def _validate_hwp_v3(content: bytes) -> None:
    if not content.startswith(HWP_V3_SIGNATURE):
        raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.")
    if len(content) < HWP_V3_FIXED_SIZE:
        raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.")

    document_info_start = len(HWP_V3_SIGNATURE)
    encrypted = int.from_bytes(
        content[document_info_start + 96 : document_info_start + 98],
        "little",
    )
    if encrypted:
        raise _invalid("ENCRYPTED_FILE", "암호화된 파일은 업로드할 수 없습니다.")
    compressed = content[document_info_start + 124]
    if compressed not in {0, 1}:
        raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.")
    information_block_size = int.from_bytes(
        content[document_info_start + 126 : document_info_start + 128],
        "little",
    )
    if HWP_V3_FIXED_SIZE + information_block_size > len(content):
        raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.")


def _ole_stream_names(document: olefile.OleFileIO) -> set[str]:
    return {"/".join(parts) for parts in document.listdir()}


def _validate_hwp(content: bytes) -> None:
    if content.startswith(HWP_V3_PREFIX):
        _validate_hwp_v3(content)
        return
    if not content.startswith(OLE_SIGNATURE):
        raise _mismatch()
    try:
        with olefile.OleFileIO(
            BytesIO(content),
            raise_defects=olefile.DEFECT_INCORRECT,
        ) as document:
            streams = _ole_stream_names(document)
            if "EncryptedPackage" in streams:
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
            if not {"DocInfo", "BodyText/Section0"}.issubset(streams):
                raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.")
            if not document.openstream("DocInfo").read():
                raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.")
            if not document.openstream("BodyText/Section0").read():
                raise _invalid("CORRUPTED_FILE", "파일 내용을 읽을 수 없습니다.")
    except (AppValidationError, UnsupportedMediaTypeError):
        raise
    except (OSError, IOError, TypeError) as error:
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
