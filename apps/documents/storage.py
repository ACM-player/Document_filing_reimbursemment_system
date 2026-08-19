import hashlib
import os
import stat
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID

from django.conf import settings


class StorageError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class StagedFile:
    path: Path
    file_size: int
    sha256: str


def _safe_relative_parts(relative_key: str) -> tuple[str, ...]:
    if not relative_key or "\x00" in relative_key or "\\" in relative_key:
        raise StorageError("unsafe_storage_key", "存储键不是安全的相对路径。")
    if relative_key.startswith("/") or (
        len(relative_key) >= 2 and relative_key[0].isalpha() and relative_key[1] == ":"
    ):
        raise StorageError("unsafe_storage_key", "存储键不是安全的相对路径。")
    parts = PurePosixPath(relative_key).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise StorageError("unsafe_storage_key", "存储键不是安全的相对路径。")
    return parts


class ControlledFileStorage:
    def __init__(
        self,
        *,
        media_root: Path | None = None,
        staging_root: Path | None = None,
        max_upload_size: int | None = None,
    ):
        self.media_root = Path(media_root or settings.MEDIA_ROOT).resolve()
        self.staging_root = Path(staging_root or settings.LABARCHIVE_STAGING_ROOT).resolve()
        self.max_upload_size = (
            settings.LABARCHIVE_MAX_UPLOAD_SIZE if max_upload_size is None else max_upload_size
        )

    def ensure_roots(self) -> None:
        self.media_root.mkdir(mode=0o750, parents=True, exist_ok=True)
        self.staging_root.mkdir(mode=0o750, parents=True, exist_ok=True)
        if self.media_root.stat().st_dev != self.staging_root.stat().st_dev:
            raise StorageError(
                "storage_filesystem_mismatch",
                "临时目录与最终目录必须位于同一文件系统。",
            )

    def staging_path(self, asset_id: UUID) -> Path:
        return self.staging_root / f"{asset_id.hex}.part"

    def stored_filename(self, asset_id: UUID, extension: str) -> str:
        normalized_extension = extension.lower()
        if (
            normalized_extension not in settings.LABARCHIVE_ALLOWED_UPLOAD_EXTENSIONS
            or not normalized_extension.startswith(".")
            or not normalized_extension[1:].isalnum()
        ):
            raise StorageError("unsupported_extension", "文件扩展名不在允许列表中。")
        return f"{asset_id.hex}{normalized_extension}"

    def final_key(self, project_id: UUID, asset_id: UUID, extension: str) -> str:
        filename = self.stored_filename(asset_id, extension)
        return f"projects/{project_id.hex}/documents/{asset_id.hex[:2]}/{filename}"

    def resolve_final(self, relative_key: str) -> Path:
        candidate = self.media_root.joinpath(*_safe_relative_parts(relative_key)).resolve()
        if not candidate.is_relative_to(self.media_root) or candidate == self.media_root:
            raise StorageError("unsafe_storage_key", "存储键越出受控目录。")
        return candidate

    def open_final(self, relative_key: str):
        parts = _safe_relative_parts(relative_key)
        candidate = self.media_root.joinpath(*parts)
        resolved_parent = candidate.parent.resolve()
        if not resolved_parent.is_relative_to(self.media_root) or candidate.is_symlink():
            raise StorageError("unsafe_storage_key", "最终文件路径越出受控目录或是链接。")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(candidate, flags)
        except FileNotFoundError as exc:
            raise StorageError("final_file_missing", "最终文件不存在。") from exc
        except OSError as exc:
            raise StorageError("final_file_unreadable", "最终文件不可安全读取。") from exc
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            os.close(descriptor)
            raise StorageError("final_file_not_regular", "最终文件不是普通文件。")
        return os.fdopen(descriptor, "rb")

    def stage_chunks(self, asset_id: UUID, chunks: Iterable[bytes]) -> StagedFile:
        self.ensure_roots()
        path = self.staging_path(asset_id)
        digest = hashlib.sha256()
        file_size = 0
        try:
            with path.open("xb") as staged:
                os.chmod(path, 0o640)
                for chunk in chunks:
                    if not isinstance(chunk, bytes):
                        raise StorageError("invalid_upload_chunk", "上传流必须提供字节数据。")
                    if not chunk:
                        continue
                    file_size += len(chunk)
                    if file_size > self.max_upload_size:
                        raise StorageError("file_too_large", "上传文件超过大小上限。")
                    digest.update(chunk)
                    staged.write(chunk)
                staged.flush()
                os.fsync(staged.fileno())
            if file_size == 0:
                raise StorageError("empty_file", "不能上传空文件。")
        except FileExistsError as exc:
            raise StorageError("staging_file_exists", "该文件已存在临时写入。") from exc
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return StagedFile(path=path, file_size=file_size, sha256=digest.hexdigest())

    def promote(self, staged_path: Path, relative_key: str) -> Path:
        self.ensure_roots()
        source = Path(staged_path).resolve()
        if source.parent != self.staging_root or not source.is_file():
            raise StorageError("invalid_staging_file", "临时文件不属于受控 staging 目录。")
        destination = self.resolve_final(relative_key)
        destination.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        if destination.exists():
            raise StorageError("final_file_exists", "最终存储键已存在，不能覆盖不可变文件。")
        os.replace(source, destination)
        os.chmod(destination, 0o640)
        return destination

    def discard_staged(self, staged_path: Path) -> bool:
        path = Path(staged_path).resolve()
        if path.parent != self.staging_root:
            raise StorageError("invalid_staging_file", "临时文件不属于受控 staging 目录。")
        existed = path.exists()
        path.unlink(missing_ok=True)
        return existed
