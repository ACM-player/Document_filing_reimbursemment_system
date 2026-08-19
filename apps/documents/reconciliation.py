from dataclasses import dataclass, field
from datetime import UTC, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditAction, AuditResult
from apps.audit.services import record_audit_event

from .models import Document, FileAsset, FileStorageStatus
from .scanning import MalwareScanner, ScanResult, scan_allows_release, scan_file
from .services import (
    DocumentUploadError,
    _lock_actor,
    _lock_document_and_asset,
    _lock_projects,
    _sha256_from_open_file,
    _status_reason,
    resume_temporary_upload,
)
from .storage import ControlledFileStorage, StorageError
from .validation import FileValidationError, ValidatedFile, validate_staged_file


class ReconciliationValidationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class ReconciliationReport:
    task_id: UUID
    checked_assets: int = 0
    resumed_uploads: int = 0
    quarantined_uploads: int = 0
    marked_missing: int = 0
    restored_missing: int = 0
    cleaned_staging: int = 0
    orphan_final_keys: list[str] = field(default_factory=list)
    orphan_staging_entries: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


def _task_request(task_id: UUID):
    return SimpleNamespace(request_id=task_id, META={})


def _copy_and_validate_final(
    *,
    asset: FileAsset,
    storage: ControlledFileStorage,
    scanner: MalwareScanner | None,
) -> tuple[ValidatedFile, ScanResult]:
    staged = None
    try:
        with storage.open_final(asset.relative_path) as final_file:
            staged = storage.stage_chunks(
                uuid4(),
                iter(lambda: final_file.read(1024 * 1024), b""),
            )
        validated = validate_staged_file(
            staged.path,
            asset.original_filename,
            expected_size=asset.file_size,
            expected_sha256=asset.sha256,
        )
        if validated.detected_mime_type != asset.detected_mime_type:
            raise ReconciliationValidationError(
                "detected_mime_mismatch",
                "文件服务端类型与入库记录不一致。",
            )
        scan_result = scan_file(staged.path, scanner)
        if not scan_allows_release(scan_result):
            raise ReconciliationValidationError(
                scan_result.reason_code or "scan_not_releasable",
                "文件扫描状态不允许恢复为可用。",
            )
        return validated, scan_result
    finally:
        if staged is not None:
            storage.discard_staged(staged.path)


@transaction.atomic
def _mark_available_asset_missing(*, asset_id: UUID, reason: str, task_id: UUID) -> bool:
    hint = (
        Document.all_objects.select_related("file_asset")
        .only("id", "project_id", "uploaded_by_id", "file_asset__id")
        .filter(file_asset_id=asset_id)
        .first()
    )
    if hint is None:
        return False
    _lock_actor(hint.uploaded_by)
    project = _lock_projects({hint.project_id})[hint.project_id]
    document, asset = _lock_document_and_asset(hint.pk)
    document.project = project
    if asset.storage_status != FileStorageStatus.AVAILABLE:
        return False
    old_status = asset.storage_status
    asset.storage_status = FileStorageStatus.MISSING
    asset.status_reason = _status_reason(reason)
    asset.save(update_fields={"storage_status", "status_reason", "updated_at"})
    if reason not in {
        "final_file_missing",
        "final_file_unreadable",
        "final_file_not_regular",
        "unsafe_storage_key",
    }:
        record_audit_event(
            action=AuditAction.FILE_INTEGRITY_FAILED,
            actor=None,
            subject=document,
            description="存储核对发现文件完整性或安全状态异常",
            old_value={"asset_status": old_status},
            new_value={"asset_status": FileStorageStatus.MISSING, "reason": reason},
            result=AuditResult.FAILED,
            task_id=task_id,
        )
    record_audit_event(
        action=AuditAction.FILE_MARKED_MISSING,
        actor=None,
        subject=document,
        description="存储核对将不可安全读取的文件标记为缺失",
        old_value={"asset_status": old_status},
        new_value={"asset_status": FileStorageStatus.MISSING, "reason": reason},
        result=AuditResult.FAILED,
        task_id=task_id,
    )
    return True


@transaction.atomic
def _restore_missing_asset(
    *,
    asset_id: UUID,
    validated: ValidatedFile,
    scan_result: ScanResult,
    storage: ControlledFileStorage,
    task_id: UUID,
) -> bool:
    hint = (
        Document.all_objects.select_related("file_asset")
        .only("id", "project_id", "uploaded_by_id", "file_asset__id")
        .filter(file_asset_id=asset_id)
        .first()
    )
    if hint is None:
        return False
    _lock_actor(hint.uploaded_by)
    project = _lock_projects({hint.project_id})[hint.project_id]
    document, asset = _lock_document_and_asset(hint.pk)
    document.project = project
    if (
        document.deleted_at is not None
        or project.deleted_at is not None
        or asset.storage_status != FileStorageStatus.MISSING
    ):
        return False
    if (
        asset.file_size != validated.file_size
        or asset.sha256 != validated.sha256
        or asset.detected_mime_type != validated.detected_mime_type
    ):
        return False
    try:
        with storage.open_final(asset.relative_path) as final_file:
            actual_size = final_file.seek(0, 2)
            actual_sha256 = _sha256_from_open_file(final_file)
    except StorageError:
        return False
    if actual_size != validated.file_size or actual_sha256 != validated.sha256:
        return False
    old_status = asset.storage_status
    asset.storage_status = FileStorageStatus.AVAILABLE
    asset.status_reason = ""
    asset.malware_scan_status = scan_result.status
    asset.save(
        update_fields={
            "storage_status",
            "status_reason",
            "malware_scan_status",
            "updated_at",
        }
    )
    record_audit_event(
        action=AuditAction.FILE_RECONCILED,
        actor=None,
        subject=document,
        description="存储核对重新验证物理文件并恢复可用状态",
        old_value={"asset_status": old_status},
        new_value={"asset_status": FileStorageStatus.AVAILABLE},
        task_id=task_id,
    )
    return True


def _failure_code(exc: Exception) -> str:
    return getattr(exc, "code", exc.__class__.__name__)


def _clean_stale_staging_entry(
    *,
    entry: Path,
    storage: ControlledFileStorage,
    task_id: UUID,
) -> None:
    quarantined = storage.quarantine_staging_entry(entry, task_id)
    try:
        record_audit_event(
            action=AuditAction.FILE_STAGING_CLEANED,
            actor=None,
            description="过期暂存文件已从活动 staging 原子移出并安排清理",
            new_value={"staging_name": entry.name},
            task_id=task_id,
        )
    except Exception:
        storage.restore_quarantined_staging(quarantined, entry)
        raise
    storage.purge_quarantined_staging(quarantined)


def reconcile_document_storage(
    *,
    storage: ControlledFileStorage | None = None,
    scanner: MalwareScanner | None = None,
    now=None,
    stale_after: timedelta | None = None,
    task_id: UUID | None = None,
) -> ReconciliationReport:
    active_storage = storage or ControlledFileStorage()
    if settings.LABARCHIVE_REQUIRE_MALWARE_SCAN and scanner is None:
        raise ValidationError("生产核对必须配置真实恶意软件扫描器。")
    active_storage.ensure_roots()
    current_time = now or timezone.now()
    maximum_age = (
        stale_after
        if stale_after is not None
        else timedelta(seconds=settings.LABARCHIVE_STAGING_MAX_AGE_SECONDS)
    )
    if maximum_age <= timedelta(0):
        raise ValidationError("stale_after 必须大于 0。")
    cutoff = current_time - maximum_age
    report = ReconciliationReport(task_id=task_id or uuid4())
    request_context = _task_request(report.task_id)

    stale_temporary_documents = list(
        Document.all_objects.select_related("file_asset", "uploaded_by")
        .filter(
            file_asset__storage_status=FileStorageStatus.TEMPORARY,
            file_asset__updated_at__lte=cutoff,
        )
        .order_by("file_asset_id")
    )
    for document in stale_temporary_documents:
        try:
            recovered = resume_temporary_upload(
                actor=document.uploaded_by,
                document=document,
                storage=active_storage,
                scanner=scanner,
                http_request=request_context,
            )
        except (DocumentUploadError, PermissionDenied, ValidationError, StorageError) as exc:
            current_status = FileAsset.objects.get(pk=document.file_asset_id).storage_status
            if current_status == FileStorageStatus.QUARANTINED:
                report.quarantined_uploads += 1
            report.failures.append(f"temporary:{document.file_asset_id}:{_failure_code(exc)}")
        else:
            if recovered.file_asset.storage_status == FileStorageStatus.AVAILABLE:
                report.resumed_uploads += 1

    assets = list(
        FileAsset.objects.filter(
            storage_status__in=(FileStorageStatus.AVAILABLE, FileStorageStatus.MISSING)
        ).order_by("pk")
    )
    for asset in assets:
        report.checked_assets += 1
        try:
            validated, scan_result = _copy_and_validate_final(
                asset=asset,
                storage=active_storage,
                scanner=scanner,
            )
        except (FileValidationError, ReconciliationValidationError, StorageError) as exc:
            reason = _failure_code(exc)
            if asset.storage_status == FileStorageStatus.AVAILABLE:
                if _mark_available_asset_missing(
                    asset_id=asset.pk,
                    reason=reason,
                    task_id=report.task_id,
                ):
                    report.marked_missing += 1
            else:
                report.failures.append(f"missing:{asset.pk}:{reason}")
            continue
        if asset.storage_status == FileStorageStatus.MISSING and _restore_missing_asset(
            asset_id=asset.pk,
            validated=validated,
            scan_result=scan_result,
            storage=active_storage,
            task_id=report.task_id,
        ):
            report.restored_missing += 1

    referenced_keys = set(FileAsset.objects.values_list("relative_path", flat=True))
    report.orphan_final_keys.extend(
        key for key in active_storage.iter_final_keys() if key not in referenced_keys
    )
    for key in report.orphan_final_keys:
        record_audit_event(
            action=AuditAction.FILE_ORPHAN_DETECTED,
            actor=None,
            description="最终存储目录中发现无数据库引用的文件，仅报告不删除",
            new_value={"relative_path": key, "action": "reported_only"},
            task_id=report.task_id,
        )

    temporary_asset_ids = set(
        FileAsset.objects.filter(storage_status=FileStorageStatus.TEMPORARY).values_list(
            "pk", flat=True
        )
    )
    for entry in active_storage.iter_staging_entries():
        try:
            modified_at = timezone.datetime.fromtimestamp(entry.lstat().st_mtime, tz=UTC)
        except OSError as exc:
            report.failures.append(f"staging:{entry.name}:{exc.__class__.__name__}")
            continue
        if modified_at > cutoff:
            continue
        try:
            entry_asset_id = UUID(hex=entry.stem)
        except (TypeError, ValueError):
            entry_asset_id = None
        if entry_asset_id in temporary_asset_ids:
            report.orphan_staging_entries.append(entry.name)
            continue
        try:
            _clean_stale_staging_entry(
                entry=entry,
                storage=active_storage,
                task_id=report.task_id,
            )
        except Exception as exc:
            report.failures.append(f"staging:{entry.name}:{_failure_code(exc)}")
        else:
            report.cleaned_staging += 1

    return report
