from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from apps.audit.models import AuditAction, AuditLog
from apps.documents.models import (
    Document,
    DocumentCategory,
    FileAsset,
    FileStorageStatus,
    MalwareScanStatus,
)
from apps.documents.scanning import ScanResult
from apps.documents.services import (
    DocumentUploadError,
    resume_temporary_upload,
    upload_document,
)
from apps.documents.storage import ControlledFileStorage, StorageError
from apps.projects.models import ProjectStatus

from .project_factories import make_project, make_user

pytestmark = pytest.mark.django_db

PDF_BYTES = b"%PDF-1.7\nphase-three-upload\n%%EOF\n"


def _storage(tmp_path, storage_class=ControlledFileStorage, **kwargs):
    media_root = tmp_path / "media"
    return storage_class(
        media_root=media_root,
        staging_root=media_root / ".staging",
        **kwargs,
    )


def _uploaded(name="evidence.pdf", content=PDF_BYTES):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


def _upload(*, actor, project, category, storage, token=None, uploaded_file=None, scanner=None):
    return upload_document(
        actor=actor,
        project=project,
        category=category,
        uploaded_file=uploaded_file or _uploaded(),
        upload_token=token or uuid4(),
        title="阶段三证据",
        storage=storage,
        scanner=scanner,
    )


@pytest.fixture
def upload_context(tmp_path):
    actor = make_user("upload-service-pi")
    project = make_project(pi=actor, code="UPLOAD-SERVICE")
    category = DocumentCategory.objects.create(code="EVIDENCE", name="证据")
    return actor, project, category, _storage(tmp_path)


def test_successful_upload_publishes_available_asset_and_audits(upload_context):
    actor, project, category, storage = upload_context

    outcome = _upload(actor=actor, project=project, category=category, storage=storage)

    assert outcome.is_replay is False
    document = Document.all_objects.select_related("file_asset").get(pk=outcome.document.pk)
    asset = document.file_asset
    assert asset.storage_status == FileStorageStatus.AVAILABLE
    assert asset.malware_scan_status == MalwareScanStatus.NOT_CONFIGURED
    assert asset.file_size == len(PDF_BYTES)
    assert len(asset.sha256) == 64
    assert asset.detected_mime_type == "application/pdf"
    assert storage.resolve_final(asset.relative_path).read_bytes() == PDF_BYTES
    assert not storage.staging_path(asset.pk).exists()
    assert (
        AuditLog.objects.filter(
            action=AuditAction.FILE_UPLOADED,
            object_id=str(document.pk),
        ).count()
        == 1
    )


def test_same_token_replays_same_result_without_consuming_new_file(upload_context):
    actor, project, category, storage = upload_context
    token = uuid4()
    first = _upload(
        actor=actor,
        project=project,
        category=category,
        storage=storage,
        token=token,
    )

    replay = _upload(
        actor=actor,
        project=project,
        category=category,
        storage=storage,
        token=token,
        uploaded_file=_uploaded(content=b"%PDF-1.7\ndifferent\n%%EOF"),
    )

    assert replay.is_replay is True
    assert replay.document.pk == first.document.pk
    assert FileAsset.objects.filter(upload_token=token).count() == 1
    assert Document.all_objects.count() == 1
    assert AuditLog.objects.filter(action=AuditAction.FILE_UPLOADED).count() == 1
    asset = FileAsset.objects.get(upload_token=token)
    assert storage.resolve_final(asset.relative_path).read_bytes() == PDF_BYTES


def test_equal_sha_with_distinct_tokens_creates_independent_assets(upload_context):
    actor, project, category, storage = upload_context

    first = _upload(actor=actor, project=project, category=category, storage=storage)
    second = _upload(actor=actor, project=project, category=category, storage=storage)

    first_asset = FileAsset.objects.get(document=first.document)
    second_asset = FileAsset.objects.get(document=second.document)
    assert first.document.pk != second.document.pk
    assert first_asset.pk != second_asset.pk
    assert first_asset.sha256 == second_asset.sha256
    assert first_asset.relative_path != second_asset.relative_path
    assert AuditLog.objects.filter(action=AuditAction.FILE_UPLOADED).count() == 2


def test_replay_token_cannot_be_reused_by_another_actor(upload_context):
    actor, project, category, storage = upload_context
    token = uuid4()
    _upload(
        actor=actor,
        project=project,
        category=category,
        storage=storage,
        token=token,
    )
    other = make_user("upload-token-other")

    with pytest.raises(PermissionDenied):
        _upload(
            actor=other,
            project=project,
            category=category,
            storage=storage,
            token=token,
        )

    assert FileAsset.objects.filter(upload_token=token).count() == 1


def test_non_writer_and_cross_project_category_are_rejected_with_no_asset(upload_context):
    actor, project, category, storage = upload_context
    reader = make_user("upload-service-reader")

    with pytest.raises(PermissionDenied):
        _upload(actor=reader, project=project, category=category, storage=storage)
    assert FileAsset.objects.count() == 0

    other_project = make_project(
        pi=actor,
        project_type=project.project_type,
        code="UPLOAD-OTHER",
    )
    other_category = DocumentCategory.objects.create(
        project=other_project,
        code="OTHER",
        name="其他项目分类",
    )
    with pytest.raises(DocumentUploadError) as exc_info:
        _upload(actor=actor, project=project, category=other_category, storage=storage)
    assert exc_info.value.code == "invalid_category"
    assert FileAsset.objects.count() == 0
    assert AuditLog.objects.filter(action=AuditAction.FILE_UPLOAD_FAILED).count() == 1


@pytest.mark.parametrize(
    ("uploaded_file", "expected_code"),
    [
        (_uploaded(name="fake.pdf", content=b"not-a-pdf"), "type_mismatch"),
        (_uploaded(name="legacy.doc", content=b"legacy"), "unsupported_extension"),
    ],
)
def test_invalid_files_fail_with_persistent_audit_or_quarantine(
    upload_context,
    uploaded_file,
    expected_code,
):
    actor, project, category, storage = upload_context

    with pytest.raises(DocumentUploadError) as exc_info:
        _upload(
            actor=actor,
            project=project,
            category=category,
            storage=storage,
            uploaded_file=uploaded_file,
        )

    assert exc_info.value.code == expected_code
    assert AuditLog.objects.filter(action=AuditAction.FILE_UPLOAD_FAILED).count() == 1
    if expected_code == "type_mismatch":
        asset = FileAsset.objects.get()
        assert asset.storage_status == FileStorageStatus.QUARANTINED
        assert asset.status_reason == expected_code
        assert storage.staging_path(asset.pk).exists()
        assert AuditLog.objects.filter(action=AuditAction.FILE_QUARANTINED).count() == 1
    else:
        assert FileAsset.objects.count() == 0


def test_oversize_stream_cleans_partial_staging_and_quarantines_intent(upload_context, tmp_path):
    actor, project, category, _ = upload_context
    storage = _storage(tmp_path / "small", max_upload_size=8)

    with pytest.raises(DocumentUploadError) as exc_info:
        _upload(actor=actor, project=project, category=category, storage=storage)

    assert exc_info.value.code == "file_too_large"
    asset = FileAsset.objects.get()
    assert asset.storage_status == FileStorageStatus.QUARANTINED
    assert not storage.staging_path(asset.pk).exists()


@override_settings(LABARCHIVE_REQUIRE_MALWARE_SCAN=True)
def test_production_policy_quarantines_when_scanner_is_not_configured(upload_context):
    actor, project, category, storage = upload_context

    with pytest.raises(DocumentUploadError) as exc_info:
        _upload(actor=actor, project=project, category=category, storage=storage)

    assert exc_info.value.code == "scan_not_releasable"
    asset = FileAsset.objects.get()
    assert asset.storage_status == FileStorageStatus.QUARANTINED
    assert asset.malware_scan_status == MalwareScanStatus.NOT_CONFIGURED
    assert storage.staging_path(asset.pk).exists()


@override_settings(LABARCHIVE_REQUIRE_MALWARE_SCAN=True)
def test_production_policy_releases_only_explicit_clean_scan(upload_context):
    actor, project, category, storage = upload_context

    outcome = _upload(
        actor=actor,
        project=project,
        category=category,
        storage=storage,
        scanner=_Scanner(ScanResult(MalwareScanStatus.CLEAN, "clean")),
    )

    assert outcome.document.file_asset.storage_status == FileStorageStatus.AVAILABLE
    assert outcome.document.file_asset.malware_scan_status == MalwareScanStatus.CLEAN


class _Scanner:
    def __init__(self, result):
        self.result = result

    def scan(self, path):
        assert path.is_file()
        return self.result


class _FailingPromoteStorage(ControlledFileStorage):
    def promote(self, staged_path, relative_key):
        raise StorageError("move_failed", "模拟原子发布失败。")


def test_move_failure_keeps_staging_and_commits_quarantine(upload_context, tmp_path):
    actor, project, category, _ = upload_context
    storage = _storage(tmp_path / "move-failure", storage_class=_FailingPromoteStorage)

    with pytest.raises(DocumentUploadError) as exc_info:
        _upload(actor=actor, project=project, category=category, storage=storage)

    assert exc_info.value.code == "move_failed"
    asset = FileAsset.objects.get()
    assert asset.storage_status == FileStorageStatus.QUARANTINED
    assert storage.staging_path(asset.pk).exists()
    assert not storage.resolve_final(asset.relative_path).exists()


class _ArchiveAfterPromoteStorage(ControlledFileStorage):
    project_id = None

    def promote(self, staged_path, relative_key):
        final_path = super().promote(staged_path, relative_key)
        from apps.projects.models import Project

        Project.all_objects.filter(pk=self.project_id).update(status=ProjectStatus.ARCHIVED)
        return final_path


class _DeleteAfterPromoteStorage(ControlledFileStorage):
    def promote(self, staged_path, relative_key):
        final_path = super().promote(staged_path, relative_key)
        final_path.unlink()
        return final_path


class _TamperAfterPromoteStorage(ControlledFileStorage):
    def promote(self, staged_path, relative_key):
        final_path = super().promote(staged_path, relative_key)
        tampered = PDF_BYTES.replace(b"upload", b"unsafe")
        assert len(tampered) == len(PDF_BYTES)
        final_path.write_bytes(tampered)
        return final_path


def test_finalization_quarantines_when_published_file_disappears(upload_context, tmp_path):
    actor, project, category, _ = upload_context
    storage = _storage(tmp_path / "missing-after-move", storage_class=_DeleteAfterPromoteStorage)

    with pytest.raises(DocumentUploadError) as exc_info:
        _upload(actor=actor, project=project, category=category, storage=storage)

    assert exc_info.value.code == "finalization_failed"
    asset = FileAsset.objects.get()
    assert asset.storage_status == FileStorageStatus.QUARANTINED
    assert asset.status_reason == "final_file_missing"
    assert AuditLog.objects.filter(action=AuditAction.FILE_QUARANTINED).count() == 1


def test_finalization_quarantines_same_size_change_after_publish(upload_context, tmp_path):
    actor, project, category, _ = upload_context
    storage = _storage(tmp_path / "changed-after-move", storage_class=_TamperAfterPromoteStorage)

    with pytest.raises(DocumentUploadError) as exc_info:
        _upload(actor=actor, project=project, category=category, storage=storage)

    assert exc_info.value.code == "finalization_failed"
    asset = FileAsset.objects.get()
    assert asset.storage_status == FileStorageStatus.QUARANTINED
    assert asset.status_reason == "final_file_changed"


class _ArchiveDuringScan:
    def __init__(self, project_id):
        self.project_id = project_id

    def scan(self, path):
        assert path.is_file()
        from apps.projects.models import Project

        Project.all_objects.filter(pk=self.project_id).update(status=ProjectStatus.ARCHIVED)
        return ScanResult(MalwareScanStatus.NOT_CONFIGURED, "scanner_not_configured")


def test_pre_publish_lock_recheck_quarantines_when_project_changes_during_scan(
    upload_context,
):
    actor, project, category, storage = upload_context

    with pytest.raises(DocumentUploadError) as exc_info:
        _upload(
            actor=actor,
            project=project,
            category=category,
            storage=storage,
            scanner=_ArchiveDuringScan(project.pk),
        )

    assert exc_info.value.code == "authorization_changed_before_publish"
    asset = FileAsset.objects.get()
    assert asset.storage_status == FileStorageStatus.QUARANTINED
    assert asset.status_reason == "authorization_changed_before_publish"
    assert storage.staging_path(asset.pk).is_file()
    assert not storage.resolve_final(asset.relative_path).exists()


def test_final_lock_recheck_quarantines_when_project_changes_after_move(upload_context, tmp_path):
    actor, project, category, _ = upload_context
    storage = _storage(tmp_path / "archive-after-move", storage_class=_ArchiveAfterPromoteStorage)
    storage.project_id = project.pk

    with pytest.raises(DocumentUploadError) as exc_info:
        _upload(actor=actor, project=project, category=category, storage=storage)

    assert exc_info.value.code == "finalization_failed"
    asset = FileAsset.objects.get()
    assert asset.storage_status == FileStorageStatus.QUARANTINED
    assert asset.status_reason == "authorization_changed_after_publish"
    assert storage.resolve_final(asset.relative_path).is_file()


def test_audit_failure_leaves_reconcilable_temporary_record_and_final_file(
    upload_context,
):
    actor, project, category, storage = upload_context

    with patch(
        "apps.documents.services.record_audit_event",
        side_effect=RuntimeError("audit unavailable"),
    ):
        with pytest.raises(DocumentUploadError) as exc_info:
            _upload(actor=actor, project=project, category=category, storage=storage)

    assert exc_info.value.code == "upload_interrupted"
    asset = FileAsset.objects.get()
    assert asset.storage_status == FileStorageStatus.TEMPORARY
    assert asset.file_size == len(PDF_BYTES)
    assert len(asset.sha256) == 64
    assert storage.resolve_final(asset.relative_path).is_file()
    assert not storage.staging_path(asset.pk).exists()

    recovered = resume_temporary_upload(
        actor=actor,
        document=exc_info.value.document,
        storage=storage,
    )
    recovered_asset = FileAsset.objects.get(pk=recovered.file_asset_id)
    assert recovered_asset.storage_status == FileStorageStatus.AVAILABLE
    assert AuditLog.objects.filter(action=AuditAction.FILE_UPLOADED).count() == 1


def test_resume_without_staging_or_final_file_commits_quarantine(upload_context):
    actor, project, category, storage = upload_context
    token = uuid4()
    with patch(
        "apps.documents.services.ControlledFileStorage.stage_chunks",
        side_effect=RuntimeError("interrupted before staging"),
    ):
        with pytest.raises(DocumentUploadError):
            _upload(
                actor=actor,
                project=project,
                category=category,
                storage=storage,
                token=token,
            )
    document = Document.all_objects.get(file_asset__upload_token=token)

    with pytest.raises(DocumentUploadError) as exc_info:
        resume_temporary_upload(actor=actor, document=document, storage=storage)

    assert exc_info.value.code == "temporary_file_missing"
    asset = FileAsset.objects.get(upload_token=token)
    assert asset.storage_status == FileStorageStatus.QUARANTINED
    assert asset.quarantined_at is not None


def test_resume_rejects_symlinked_final_file(upload_context):
    actor, project, category, storage = upload_context

    with patch(
        "apps.documents.services.record_audit_event",
        side_effect=RuntimeError("audit unavailable"),
    ):
        with pytest.raises(DocumentUploadError) as exc_info:
            _upload(actor=actor, project=project, category=category, storage=storage)

    document = Document.all_objects.select_related("file_asset").get(pk=exc_info.value.document.pk)
    final_path = storage.resolve_final(document.file_asset.relative_path)
    target = storage.media_root / "safe-target.pdf"
    target.write_bytes(PDF_BYTES)
    final_path.unlink()
    final_path.symlink_to(target)

    with pytest.raises(DocumentUploadError) as resume_error:
        resume_temporary_upload(actor=actor, document=document, storage=storage)

    assert resume_error.value.code == "unsafe_storage_key"
    asset = FileAsset.objects.get(pk=document.file_asset_id)
    assert asset.storage_status == FileStorageStatus.QUARANTINED
