import hashlib
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

from django.conf import settings


class FileValidationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ValidatedFile:
    original_filename: str
    extension: str
    detected_mime_type: str
    file_size: int
    sha256: str


@dataclass(frozen=True)
class ZipInspection:
    members: frozenset[str]
    total_uncompressed_size: int


MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".zip": "application/zip",
}

_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_IEND = b"\x00\x00\x00\x00IEND\xaeB\x60\x82"


def normalize_original_filename(filename: str) -> tuple[str, str]:
    normalized = filename.strip()
    if (
        not normalized
        or len(normalized) > 255
        or "\x00" in normalized
        or "/" in normalized
        or "\\" in normalized
    ):
        raise FileValidationError("unsafe_filename", "文件名无效或包含路径信息。")
    extension = Path(normalized).suffix.lower()
    if extension not in settings.LABARCHIVE_ALLOWED_UPLOAD_EXTENSIONS:
        raise FileValidationError("unsupported_extension", "文件扩展名不在允许列表中。")
    return normalized, extension


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    file_size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            file_size += len(chunk)
            if file_size > settings.LABARCHIVE_MAX_UPLOAD_SIZE:
                raise FileValidationError("file_too_large", "上传文件超过大小上限。")
            digest.update(chunk)
    if file_size == 0:
        raise FileValidationError("empty_file", "不能上传空文件。")
    return file_size, digest.hexdigest()


def _validate_member_path(filename: str, *, is_directory: bool) -> tuple[str, ...]:
    if not filename or "\x00" in filename or "\\" in filename:
        raise FileValidationError("unsafe_zip_path", "ZIP 包含不安全的成员路径。")
    if filename.startswith("/") or re.match(r"^[A-Za-z]:", filename):
        raise FileValidationError("unsafe_zip_path", "ZIP 包含绝对或 drive 路径。")
    raw_parts = filename.split("/")
    if is_directory and raw_parts[-1] == "":
        raw_parts.pop()
    if not raw_parts or any(part in {"", ".", ".."} for part in raw_parts):
        raise FileValidationError("unsafe_zip_path", "ZIP 包含空、点或穿越路径段。")
    parts = PurePosixPath(filename).parts
    if tuple(raw_parts) != parts:
        raise FileValidationError("unsafe_zip_path", "ZIP 成员路径不能安全规范化。")
    return parts


def _validate_member_type(info: zipfile.ZipInfo) -> None:
    unix_mode = info.external_attr >> 16
    file_type = stat.S_IFMT(unix_mode)
    allowed_types = {0, stat.S_IFREG, stat.S_IFDIR}
    if file_type not in allowed_types or stat.S_ISLNK(unix_mode):
        raise FileValidationError("unsafe_zip_member_type", "ZIP 包含链接或特殊文件。")


def inspect_zip(path: Path) -> ZipInspection:
    members = set()
    casefolded_members = set()
    total_size = 0
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > settings.LABARCHIVE_ZIP_MAX_MEMBERS:
                raise FileValidationError("zip_too_many_members", "ZIP 成员数量超过上限。")
            for info in infos:
                _validate_member_path(info.filename, is_directory=info.is_dir())
                _validate_member_type(info)
                if info.flag_bits & 0x1:
                    raise FileValidationError("encrypted_zip_member", "不允许加密 ZIP 成员。")
                if info.filename in members or info.filename.casefold() in casefolded_members:
                    raise FileValidationError("duplicate_zip_member", "ZIP 包含重复成员路径。")
                members.add(info.filename)
                casefolded_members.add(info.filename.casefold())
                if info.file_size > settings.LABARCHIVE_ZIP_MAX_MEMBER_SIZE:
                    raise FileValidationError("zip_member_too_large", "ZIP 单成员大小超过上限。")
                total_size += info.file_size
                if total_size > settings.LABARCHIVE_ZIP_MAX_TOTAL_SIZE:
                    raise FileValidationError("zip_total_too_large", "ZIP 解压后总大小超过上限。")
                if info.file_size and not info.compress_size:
                    raise FileValidationError("zip_ratio_too_high", "ZIP 成员压缩倍率超过上限。")
                if info.compress_size:
                    ratio = info.file_size / info.compress_size
                    if ratio > settings.LABARCHIVE_ZIP_MAX_COMPRESSION_RATIO:
                        raise FileValidationError(
                            "zip_ratio_too_high", "ZIP 成员压缩倍率超过上限。"
                        )
                if info.is_dir():
                    continue
                if info.filename.lower().endswith(".zip"):
                    raise FileValidationError("nested_zip", "不允许嵌套 ZIP。")
                with archive.open(info) as member:
                    prefix = member.read(4)
                    if prefix.startswith(_ZIP_SIGNATURES):
                        raise FileValidationError("nested_zip", "不允许嵌套 ZIP。")
                    while member.read(1024 * 1024):
                        pass
    except FileValidationError:
        raise
    except (OSError, RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
        raise FileValidationError("invalid_zip", "ZIP 容器损坏或使用不支持的格式。") from exc
    return ZipInspection(frozenset(members), total_size)


def _read_safe_xml(archive: zipfile.ZipFile, member_name: str) -> ElementTree.Element:
    try:
        info = archive.getinfo(member_name)
    except KeyError as exc:
        raise FileValidationError("invalid_ooxml", "OOXML 缺少必要结构。") from exc
    if info.file_size > settings.LABARCHIVE_OOXML_METADATA_MAX_SIZE:
        raise FileValidationError("ooxml_metadata_too_large", "OOXML 元数据超过安全上限。")
    try:
        content = archive.read(info)
        if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
            raise FileValidationError("unsafe_ooxml_xml", "OOXML 元数据包含不允许的声明。")
        return ElementTree.fromstring(content)
    except FileValidationError:
        raise
    except (ElementTree.ParseError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise FileValidationError("invalid_ooxml", "OOXML 元数据损坏。") from exc


def _validate_ooxml(path: Path, extension: str) -> None:
    inspection = inspect_zip(path)
    required_part = "word/document.xml" if extension == ".docx" else "xl/workbook.xml"
    required_names = {"[Content_Types].xml", "_rels/.rels", required_part}
    if not required_names <= inspection.members:
        raise FileValidationError("invalid_ooxml", "OOXML 缺少必要结构。")
    if any(name.casefold().endswith("vbaproject.bin") for name in inspection.members):
        raise FileValidationError("macro_enabled_ooxml", "不允许含宏的 OOXML 文件。")
    expected_content_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
        if extension == ".docx"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
    )
    with zipfile.ZipFile(path) as archive:
        content_types = _read_safe_xml(archive, "[Content_Types].xml")
        _read_safe_xml(archive, "_rels/.rels")
        _read_safe_xml(archive, required_part)
    overrides = {
        (element.attrib.get("PartName"), element.attrib.get("ContentType"))
        for element in content_types.iter()
        if element.tag.rsplit("}", 1)[-1] == "Override"
    }
    if (f"/{required_part}", expected_content_type) not in overrides:
        raise FileValidationError("invalid_ooxml", "OOXML 主文档类型与扩展名不一致。")
    if any("macroenabled" in (content_type or "").lower() for _, content_type in overrides):
        raise FileValidationError("macro_enabled_ooxml", "不允许含宏的 OOXML 文件。")


def _detect_type(path: Path, extension: str) -> str:
    if extension in {".docx", ".xlsx"}:
        _validate_ooxml(path, extension)
        return MIME_TYPES[extension]
    if extension == ".zip":
        inspect_zip(path)
        return MIME_TYPES[extension]
    with path.open("rb") as source:
        header = source.read(16)
        source.seek(max(0, path.stat().st_size - 1024))
        tail = source.read()
    if extension == ".pdf" and header.startswith(b"%PDF-") and tail.rstrip().endswith(b"%%EOF"):
        return MIME_TYPES[extension]
    if extension == ".png" and header.startswith(_PNG_SIGNATURE) and tail.endswith(_PNG_IEND):
        return MIME_TYPES[extension]
    if (
        extension in {".jpg", ".jpeg"}
        and header.startswith(b"\xff\xd8")
        and tail.endswith(b"\xff\xd9")
    ):
        return MIME_TYPES[extension]
    raise FileValidationError("type_mismatch", "文件内容与扩展名或必要结构不一致。")


def validate_staged_file(
    path: Path,
    original_filename: str,
    *,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
) -> ValidatedFile:
    normalized_filename, extension = normalize_original_filename(original_filename)
    candidate = Path(path)
    try:
        metadata = candidate.lstat()
    except OSError as exc:
        raise FileValidationError("missing_staged_file", "临时文件不存在或不可读。") from exc
    if candidate.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise FileValidationError("invalid_staged_file", "临时对象必须是普通文件。")
    file_size, sha256 = _hash_file(candidate)
    if expected_size is not None and file_size != expected_size:
        raise FileValidationError("size_mismatch", "流式计数与临时文件大小不一致。")
    if expected_sha256 is not None and sha256 != expected_sha256.lower():
        raise FileValidationError("sha256_mismatch", "流式摘要与临时文件摘要不一致。")
    detected_mime_type = _detect_type(candidate, extension)
    return ValidatedFile(
        original_filename=normalized_filename,
        extension=extension,
        detected_mime_type=detected_mime_type,
        file_size=file_size,
        sha256=sha256,
    )
