import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Any, BinaryIO
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditAction, AuditResult
from apps.audit.services import record_audit_event
from apps.projects.models import Project
from apps.projects.permissions import is_project_portal_user

from .models import (
    Document,
    DocumentCategory,
    FileAsset,
    FileStorageStatus,
)
from .permissions import can_upload_documents, can_view_document
from .scanning import MalwareScanner, ScanResult, scan_allows_release, scan_file
from .storage import ControlledFileStorage, StagedFile, StorageError
from .validation import (
    FileValidationError,
    ValidatedFile,
    normalize_original_filename,
    validate_staged_file,
)


class DocumentUploadError(Exception):
    def __init__(self, code: str, message: str, *, document: Document | None = None):
        super().__init__(message)
        self.code = code
        self.document = document


@dataclass(frozen=True)
class UploadOutcome:
    document: Document
    is_replay: bool


@dataclass(frozen=True)
class PreparedDownload:
    document: Document
    file: BinaryIO
    filename: str
    content_type: str
    file_size: int


class DocumentDownloadError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _DownloadDecision:
    prepared: PreparedDownload | None = None
    error: DocumentDownloadError | None = None


@dataclass(frozen=True)
class _UploadIntent:
    document: Document | None = None
    error: DocumentUploadError | None = None
    is_replay: bool = False


def _lock_actor(actor) -> User:
    try:
        return User.objects.select_for_update().get(pk=getattr(actor, "pk", None))
    except User.DoesNotExist as exc:
        raise PermissionDenied("当前账号不存在或已失效。") from exc


def _lock_projects(project_ids) -> dict[UUID, Project]:
    normalized_ids = {project_id for project_id in project_ids if project_id is not None}
    projects = {
        project.pk: project
        for project in Project.all_objects.select_for_update()
        .filter(pk__in=normalized_ids)
        .order_by("pk")
    }
    if set(projects) != normalized_ids:
        raise ValidationError("项目不存在或已被删除。")
    return projects


def _find_document_for_token(upload_token: UUID) -> Document | None:
    asset = FileAsset.objects.filter(upload_token=upload_token).only("id").first()
    if asset is None:
        return None
    return Document.all_objects.filter(file_asset_id=asset.pk).only("id", "project_id").first()


def _lock_document_and_asset(document_id: UUID) -> tuple[Document, FileAsset]:
    try:
        document = (
            Document.all_objects.select_for_update(of=("self",))
            .select_related("project", "category")
            .get(pk=document_id)
        )
    except Document.DoesNotExist as exc:
        raise ValidationError("上传文档不存在。") from exc
    asset = FileAsset.objects.select_for_update().get(pk=document.file_asset_id)
    document.file_asset = asset
    return document, asset


def _audit_initial_failure(*, actor, project, code, http_request=None) -> None:
    record_audit_event(
        action=AuditAction.FILE_UPLOAD_FAILED,
        request=http_request,
        actor=actor,
        subject=project,
        description="文件上传请求在创建持久化意图前失败",
        new_value={"reason": code},
        result=AuditResult.FAILED,
    )


@transaction.atomic
def _initialize_upload(
    *,
    actor,
    project_id: UUID,
    category_id: UUID,
    original_filename: str,
    declared_mime_type: str,
    upload_token: UUID,
    title: str,
    description: str,
    document_date: date | None,
    storage: ControlledFileStorage,
    http_request=None,
) -> _UploadIntent:
    locked_actor = _lock_actor(actor)
    existing_hint = _find_document_for_token(upload_token)
    project_ids = {project_id}
    if existing_hint is not None:
        project_ids.add(existing_hint.project_id)
    projects = _lock_projects(project_ids)
    locked_project = projects[project_id]

    if existing_hint is not None:
        existing, _ = _lock_document_and_asset(existing_hint.pk)
        if (
            existing.project_id != project_id
            or existing.uploaded_by_id != locked_actor.pk
            or not can_view_document(locked_actor, existing)
        ):
            raise PermissionDenied("该上传令牌不能用于当前项目或账号。")
        return _UploadIntent(document=existing, is_replay=True)

    if not can_upload_documents(locked_actor, locked_project):
        raise PermissionDenied("当前账号无权向该项目上传文件。")

    try:
        normalized_filename, extension = normalize_original_filename(original_filename)
    except FileValidationError as exc:
        _audit_initial_failure(
            actor=locked_actor,
            project=locked_project,
            code=exc.code,
            http_request=http_request,
        )
        return _UploadIntent(error=DocumentUploadError(exc.code, str(exc)))

    try:
        category = DocumentCategory.objects.select_for_update().get(pk=category_id)
    except DocumentCategory.DoesNotExist:
        _audit_initial_failure(
            actor=locked_actor,
            project=locked_project,
            code="invalid_category",
            http_request=http_request,
        )
        return _UploadIntent(error=DocumentUploadError("invalid_category", "文档分类不存在。"))
    if not category.is_active or (
        category.project_id is not None and category.project_id != locked_project.pk
    ):
        _audit_initial_failure(
            actor=locked_actor,
            project=locked_project,
            code="invalid_category",
            http_request=http_request,
        )
        return _UploadIntent(
            error=DocumentUploadError("invalid_category", "文档分类不可用于当前项目。")
        )

    asset_id = FileAsset._meta.pk.get_default()
    stored_filename = storage.stored_filename(asset_id, extension)
    relative_path = storage.final_key(locked_project.pk, asset_id, extension)
    asset = FileAsset(
        id=asset_id,
        original_filename=normalized_filename,
        stored_filename=stored_filename,
        relative_path=relative_path,
        declared_mime_type=declared_mime_type[:255],
        upload_token=upload_token,
        uploaded_by=locked_actor,
    )
    document = Document(
        project=locked_project,
        category=category,
        file_asset=asset,
        title=title.strip(),
        description=description,
        document_date=document_date,
        uploaded_by=locked_actor,
    )
    try:
        asset.full_clean()
        document.full_clean(exclude={"file_asset"})
    except ValidationError:
        _audit_initial_failure(
            actor=locked_actor,
            project=locked_project,
            code="invalid_document_metadata",
            http_request=http_request,
        )
        return _UploadIntent(
            error=DocumentUploadError(
                "invalid_document_metadata",
                "文档元数据无效。",
            )
        )
    asset.save(force_insert=True)
    document.save(force_insert=True)
    return _UploadIntent(document=document)


def _status_reason(code: str) -> str:
    return code[:100]


@transaction.atomic
def _quarantine_upload(
    *,
    actor,
    document_id: UUID,
    reason: str,
    scan_result: ScanResult | None = None,
    staged: StagedFile | None = None,
    validated: ValidatedFile | None = None,
    http_request=None,
) -> Document:
    locked_actor = _lock_actor(actor)
    document_hint = Document.all_objects.only("project_id").get(pk=document_id)
    project = _lock_projects({document_hint.project_id})[document_hint.project_id]
    document, asset = _lock_document_and_asset(document_id)
    if document.uploaded_by_id != locked_actor.pk or document.project_id != project.pk:
        raise PermissionDenied("该上传记录不属于当前账号或项目。")
    if asset.storage_status != FileStorageStatus.TEMPORARY:
        return document
    if validated is not None:
        asset.file_size = validated.file_size
        asset.sha256 = validated.sha256
        asset.detected_mime_type = validated.detected_mime_type
    elif staged is not None:
        asset.file_size = staged.file_size
        asset.sha256 = staged.sha256
    if scan_result is not None:
        asset.malware_scan_status = scan_result.status
    asset.storage_status = FileStorageStatus.QUARANTINED
    asset.status_reason = _status_reason(reason)
    asset.quarantined_at = timezone.now()
    asset.save(
        update_fields={
            "file_size",
            "sha256",
            "detected_mime_type",
            "malware_scan_status",
            "storage_status",
            "status_reason",
            "quarantined_at",
            "updated_at",
        }
    )
    record_audit_event(
        action=AuditAction.FILE_QUARANTINED,
        request=http_request,
        actor=locked_actor,
        subject=document,
        description="文件上传未通过安全或状态门禁，资产已隔离",
        new_value={"asset_id": str(asset.pk), "reason": reason},
    )
    record_audit_event(
        action=AuditAction.FILE_UPLOAD_FAILED,
        request=http_request,
        actor=locked_actor,
        subject=document,
        description="文件上传失败",
        new_value={"asset_id": str(asset.pk), "reason": reason},
        result=AuditResult.FAILED,
    )
    return document


@transaction.atomic
def _record_validated_upload(
    *,
    actor,
    document_id: UUID,
    validated: ValidatedFile,
    scan_result: ScanResult,
    http_request=None,
) -> tuple[Document, bool]:
    locked_actor = _lock_actor(actor)
    document_hint = Document.all_objects.only("project_id").get(pk=document_id)
    project = _lock_projects({document_hint.project_id})[document_hint.project_id]
    document, asset = _lock_document_and_asset(document_id)
    if asset.storage_status != FileStorageStatus.TEMPORARY:
        return document, False
    if document.uploaded_by_id != locked_actor.pk or not can_upload_documents(
        locked_actor, project
    ):
        asset.storage_status = FileStorageStatus.QUARANTINED
        asset.status_reason = "authorization_changed_before_publish"
        asset.file_size = validated.file_size
        asset.sha256 = validated.sha256
        asset.detected_mime_type = validated.detected_mime_type
        asset.malware_scan_status = scan_result.status
        asset.quarantined_at = timezone.now()
        asset.save()
        record_audit_event(
            action=AuditAction.FILE_QUARANTINED,
            request=http_request,
            actor=locked_actor,
            subject=document,
            description="文件发布前权限变化，资产已隔离",
            new_value={"reason": asset.status_reason},
        )
        record_audit_event(
            action=AuditAction.FILE_UPLOAD_FAILED,
            request=http_request,
            actor=locked_actor,
            subject=document,
            description="文件发布前权限已变化",
            new_value={"reason": asset.status_reason},
            result=AuditResult.DENIED,
        )
        return document, False
    asset.file_size = validated.file_size
    asset.sha256 = validated.sha256
    asset.detected_mime_type = validated.detected_mime_type
    asset.malware_scan_status = scan_result.status
    asset.status_reason = ""
    asset.save(
        update_fields={
            "file_size",
            "sha256",
            "detected_mime_type",
            "malware_scan_status",
            "status_reason",
            "updated_at",
        }
    )
    return document, True


@transaction.atomic
def _finalize_upload(
    *,
    actor,
    document_id: UUID,
    storage: ControlledFileStorage,
    http_request=None,
) -> tuple[Document, bool]:
    locked_actor = _lock_actor(actor)
    document_hint = Document.all_objects.only("project_id").get(pk=document_id)
    project = _lock_projects({document_hint.project_id})[document_hint.project_id]
    document, asset = _lock_document_and_asset(document_id)
    if asset.storage_status != FileStorageStatus.TEMPORARY:
        return document, False
    if document.uploaded_by_id != locked_actor.pk or not can_upload_documents(
        locked_actor, project
    ):
        asset.storage_status = FileStorageStatus.QUARANTINED
        asset.status_reason = "authorization_changed_after_publish"
        asset.quarantined_at = timezone.now()
        asset.save(
            update_fields={
                "storage_status",
                "status_reason",
                "quarantined_at",
                "updated_at",
            }
        )
        record_audit_event(
            action=AuditAction.FILE_QUARANTINED,
            request=http_request,
            actor=locked_actor,
            subject=document,
            description="最终授权复核失败，资产已隔离",
            new_value={"reason": asset.status_reason},
        )
        record_audit_event(
            action=AuditAction.FILE_UPLOAD_FAILED,
            request=http_request,
            actor=locked_actor,
            subject=document,
            description="文件发布后最终授权复核失败",
            new_value={"reason": asset.status_reason},
            result=AuditResult.DENIED,
        )
        return document, False
    final_path = storage.resolve_final(asset.relative_path)
    if not final_path.is_file():
        asset.storage_status = FileStorageStatus.QUARANTINED
        asset.status_reason = "final_file_missing"
        asset.quarantined_at = timezone.now()
        asset.save(
            update_fields={
                "storage_status",
                "status_reason",
                "quarantined_at",
                "updated_at",
            }
        )
        record_audit_event(
            action=AuditAction.FILE_QUARANTINED,
            request=http_request,
            actor=locked_actor,
            subject=document,
            description="最终文件缺失，资产已隔离",
            new_value={"reason": asset.status_reason},
        )
        record_audit_event(
            action=AuditAction.FILE_UPLOAD_FAILED,
            request=http_request,
            actor=locked_actor,
            subject=document,
            description="最终文件不存在，上传保持隔离",
            new_value={"reason": asset.status_reason},
            result=AuditResult.FAILED,
        )
        return document, False
    asset.storage_status = FileStorageStatus.AVAILABLE
    asset.status_reason = ""
    asset.save(update_fields={"storage_status", "status_reason", "updated_at"})
    record_audit_event(
        action=AuditAction.FILE_UPLOADED,
        request=http_request,
        actor=locked_actor,
        subject=document,
        description="项目文件上传完成",
        new_value={
            "asset_id": str(asset.pk),
            "file_size": asset.file_size,
            "sha256": asset.sha256,
            "detected_mime_type": asset.detected_mime_type,
        },
    )
    return document, True


def _raise_upload_failure(code: str, message: str, document: Document) -> None:
    document.refresh_from_db()
    raise DocumentUploadError(code, message, document=document)


def upload_document(
    *,
    actor,
    project: Project,
    category: DocumentCategory,
    uploaded_file: Any,
    upload_token: UUID,
    title: str,
    description: str = "",
    document_date: date | None = None,
    storage: ControlledFileStorage | None = None,
    scanner: MalwareScanner | None = None,
    http_request=None,
) -> UploadOutcome:
    active_storage = storage or ControlledFileStorage()
    original_filename = getattr(uploaded_file, "name", "")
    declared_mime_type = getattr(uploaded_file, "content_type", "") or ""
    chunks = getattr(uploaded_file, "chunks", None)
    if not callable(chunks):
        raise DocumentUploadError("invalid_upload_stream", "上传对象不能提供分块字节流。")

    try:
        intent = _initialize_upload(
            actor=actor,
            project_id=project.pk,
            category_id=category.pk,
            original_filename=original_filename,
            declared_mime_type=declared_mime_type,
            upload_token=upload_token,
            title=title,
            description=description,
            document_date=document_date,
            storage=active_storage,
            http_request=http_request,
        )
    except IntegrityError:
        intent = _initialize_upload(
            actor=actor,
            project_id=project.pk,
            category_id=category.pk,
            original_filename=original_filename,
            declared_mime_type=declared_mime_type,
            upload_token=upload_token,
            title=title,
            description=description,
            document_date=document_date,
            storage=active_storage,
            http_request=http_request,
        )
    if intent.error is not None:
        raise intent.error
    document = intent.document
    if document is None:
        raise DocumentUploadError("upload_intent_failed", "无法建立上传意图。")
    if intent.is_replay:
        return UploadOutcome(document=document, is_replay=True)

    staged = None
    validated = None
    scan_result = None
    try:
        staged = active_storage.stage_chunks(document.file_asset_id, chunks())
        validated = validate_staged_file(
            staged.path,
            original_filename,
            expected_size=staged.file_size,
            expected_sha256=staged.sha256,
        )
        scan_result = scan_file(staged.path, scanner)
        if not scan_allows_release(scan_result):
            _quarantine_upload(
                actor=actor,
                document_id=document.pk,
                reason=scan_result.reason_code or "scan_not_releasable",
                scan_result=scan_result,
                staged=staged,
                validated=validated,
                http_request=http_request,
            )
            _raise_upload_failure("scan_not_releasable", "文件扫描状态不允许发布。", document)
        document, may_publish = _record_validated_upload(
            actor=actor,
            document_id=document.pk,
            validated=validated,
            scan_result=scan_result,
            http_request=http_request,
        )
        if not may_publish:
            _raise_upload_failure(
                "authorization_changed_before_publish",
                "上传期间权限或项目状态已变化。",
                document,
            )
        active_storage.promote(staged.path, document.file_asset.relative_path)
        document, finalized = _finalize_upload(
            actor=actor,
            document_id=document.pk,
            storage=active_storage,
            http_request=http_request,
        )
        if not finalized:
            _raise_upload_failure(
                "finalization_failed",
                "最终状态复核失败，文件未进入可用状态。",
                document,
            )
        document.refresh_from_db()
        return UploadOutcome(document=document, is_replay=False)
    except DocumentUploadError:
        raise
    except (FileValidationError, StorageError) as exc:
        _quarantine_upload(
            actor=actor,
            document_id=document.pk,
            reason=exc.code,
            scan_result=scan_result,
            staged=staged,
            validated=validated,
            http_request=http_request,
        )
        _raise_upload_failure(exc.code, str(exc), document)
    except Exception as exc:
        document.refresh_from_db()
        raise DocumentUploadError(
            "upload_interrupted",
            "上传在可恢复状态中断，请稍后由维护流程核对。",
            document=document,
        ) from exc
    raise AssertionError("unreachable")


def resume_temporary_upload(
    *,
    actor,
    document: Document,
    storage: ControlledFileStorage | None = None,
    scanner: MalwareScanner | None = None,
    http_request=None,
) -> Document:
    active_storage = storage or ControlledFileStorage()
    current = Document.all_objects.select_related("file_asset").get(pk=document.pk)
    asset = current.file_asset
    if asset.storage_status == FileStorageStatus.AVAILABLE:
        return current
    if asset.storage_status != FileStorageStatus.TEMPORARY:
        raise DocumentUploadError(
            "upload_not_resumable",
            "只有 TEMPORARY 上传可以由恢复流程续跑。",
            document=current,
        )

    final_path = active_storage.resolve_final(asset.relative_path)
    staging_path = active_storage.staging_path(asset.pk)
    candidate = final_path if final_path.is_file() else staging_path
    if not candidate.is_file():
        _quarantine_upload(
            actor=actor,
            document_id=current.pk,
            reason="temporary_file_missing",
            http_request=http_request,
        )
        _raise_upload_failure(
            "temporary_file_missing",
            "上传恢复时没有找到受控临时文件或最终文件。",
            current,
        )

    try:
        validated = validate_staged_file(
            candidate,
            asset.original_filename,
            expected_size=asset.file_size,
            expected_sha256=asset.sha256 or None,
        )
        scan_result = scan_file(candidate, scanner)
        if not scan_allows_release(scan_result):
            _quarantine_upload(
                actor=actor,
                document_id=current.pk,
                reason=scan_result.reason_code or "scan_not_releasable",
                scan_result=scan_result,
                validated=validated,
                http_request=http_request,
            )
            _raise_upload_failure(
                "scan_not_releasable",
                "恢复时文件扫描状态不允许发布。",
                current,
            )
        current, may_publish = _record_validated_upload(
            actor=actor,
            document_id=current.pk,
            validated=validated,
            scan_result=scan_result,
            http_request=http_request,
        )
        if not may_publish:
            _raise_upload_failure(
                "authorization_changed_before_publish",
                "恢复上传时权限或项目状态已变化。",
                current,
            )
        if not final_path.is_file():
            active_storage.promote(staging_path, asset.relative_path)
        current, finalized = _finalize_upload(
            actor=actor,
            document_id=current.pk,
            storage=active_storage,
            http_request=http_request,
        )
        if not finalized:
            _raise_upload_failure(
                "finalization_failed",
                "恢复上传的最终状态复核失败。",
                current,
            )
        current.refresh_from_db()
        return current
    except DocumentUploadError:
        raise
    except (FileValidationError, StorageError) as exc:
        _quarantine_upload(
            actor=actor,
            document_id=current.pk,
            reason=exc.code,
            http_request=http_request,
        )
        _raise_upload_failure(exc.code, str(exc), current)
    except Exception as exc:
        current.refresh_from_db()
        raise DocumentUploadError(
            "upload_recovery_interrupted",
            "上传恢复再次中断，记录仍保持可恢复状态。",
            document=current,
        ) from exc
    raise AssertionError("unreachable")


def _audit_download_failure(*, actor, subject, code, result, http_request=None) -> None:
    record_audit_event(
        action=AuditAction.FILE_DOWNLOADED,
        request=http_request,
        actor=actor,
        subject=subject,
        description="文件下载请求失败",
        new_value={"reason": code},
        result=result,
    )


def _sha256_from_open_file(file_object: BinaryIO) -> str:
    digest = hashlib.sha256()
    file_object.seek(0)
    while chunk := file_object.read(1024 * 1024):
        digest.update(chunk)
    file_object.seek(0)
    return digest.hexdigest()


def _prepare_document_download(
    *,
    actor,
    document_id: UUID,
    storage: ControlledFileStorage,
    http_request=None,
) -> _DownloadDecision:
    locked_actor = _lock_actor(actor)
    if not is_project_portal_user(locked_actor):
        raise PermissionDenied("当前账号无权进入项目文件系统。")
    document_hint = Document.all_objects.only("project_id").filter(pk=document_id).first()
    if document_hint is None:
        _audit_download_failure(
            actor=locked_actor,
            subject=None,
            code="document_not_found",
            result=AuditResult.DENIED,
            http_request=http_request,
        )
        return _DownloadDecision(
            error=DocumentDownloadError("document_not_found", "文件不存在或无权访问。")
        )
    project = _lock_projects({document_hint.project_id})[document_hint.project_id]
    document, asset = _lock_document_and_asset(document_id)
    document.project = project
    if not can_view_document(locked_actor, document):
        _audit_download_failure(
            actor=locked_actor,
            subject=document,
            code="download_denied",
            result=AuditResult.DENIED,
            http_request=http_request,
        )
        return _DownloadDecision(
            error=DocumentDownloadError("download_denied", "文件不存在或无权访问。")
        )
    if asset.storage_status != FileStorageStatus.AVAILABLE or asset.deleted_at is not None:
        _audit_download_failure(
            actor=locked_actor,
            subject=document,
            code="asset_unavailable",
            result=AuditResult.FAILED,
            http_request=http_request,
        )
        return _DownloadDecision(
            error=DocumentDownloadError("asset_unavailable", "文件当前不可下载。")
        )

    try:
        file_object = storage.open_final(asset.relative_path)
    except StorageError as exc:
        asset.storage_status = FileStorageStatus.MISSING
        asset.status_reason = _status_reason(exc.code)
        asset.save(update_fields={"storage_status", "status_reason", "updated_at"})
        record_audit_event(
            action=AuditAction.FILE_MARKED_MISSING,
            request=http_request,
            actor=locked_actor,
            subject=document,
            description="下载前物理文件缺失或不能安全打开",
            new_value={"asset_id": str(asset.pk), "reason": exc.code},
            result=AuditResult.FAILED,
        )
        _audit_download_failure(
            actor=locked_actor,
            subject=document,
            code=exc.code,
            result=AuditResult.FAILED,
            http_request=http_request,
        )
        return _DownloadDecision(
            error=DocumentDownloadError("asset_missing", "物理文件缺失或不可安全读取。")
        )

    actual_size = file_object.seek(0, 2)
    file_object.seek(0)
    if actual_size != asset.file_size:
        actual_sha256 = _sha256_from_open_file(file_object)
        file_object.close()
        asset.storage_status = FileStorageStatus.MISSING
        asset.status_reason = "file_metadata_mismatch"
        asset.save(update_fields={"storage_status", "status_reason", "updated_at"})
        record_audit_event(
            action=AuditAction.FILE_INTEGRITY_FAILED,
            request=http_request,
            actor=locked_actor,
            subject=document,
            description="下载前文件大小异常并完成 SHA256 复核",
            old_value={"file_size": asset.file_size, "sha256": asset.sha256},
            new_value={"file_size": actual_size, "sha256": actual_sha256},
            result=AuditResult.FAILED,
        )
        _audit_download_failure(
            actor=locked_actor,
            subject=document,
            code="file_metadata_mismatch",
            result=AuditResult.FAILED,
            http_request=http_request,
        )
        return _DownloadDecision(
            error=DocumentDownloadError("integrity_failed", "文件完整性元数据异常。")
        )

    try:
        record_audit_event(
            action=AuditAction.FILE_DOWNLOADED,
            request=http_request,
            actor=locked_actor,
            subject=document,
            description="文件已鉴权并开始受控下载",
            new_value={"asset_id": str(asset.pk), "file_size": asset.file_size},
        )
    except Exception:
        file_object.close()
        raise
    return _DownloadDecision(
        prepared=PreparedDownload(
            document=document,
            file=file_object,
            filename=asset.original_filename,
            content_type=asset.detected_mime_type,
            file_size=asset.file_size,
        )
    )


def prepare_document_download(
    *,
    actor,
    document_id: UUID,
    storage: ControlledFileStorage | None = None,
    http_request=None,
) -> PreparedDownload:
    decision = None
    try:
        with transaction.atomic():
            decision = _prepare_document_download(
                actor=actor,
                document_id=document_id,
                storage=storage or ControlledFileStorage(),
                http_request=http_request,
            )
    except Exception:
        if decision is not None and decision.prepared is not None:
            decision.prepared.file.close()
        raise
    if decision.error is not None:
        raise decision.error
    if decision.prepared is None:
        raise DocumentDownloadError("download_failed", "文件下载准备失败。")
    return decision.prepared
