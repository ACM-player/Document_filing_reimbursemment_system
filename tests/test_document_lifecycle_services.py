from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.constants import LAB_MEMBER_GROUP, SYSTEM_ADMIN_GROUP
from apps.audit.models import AuditAction, AuditLog, AuditResult
from apps.documents.models import Document, FileStorageStatus
from apps.documents.scanning import ScanResult
from apps.documents.services import (
    DocumentLifecycleError,
    recycle_bin_documents_for,
    restore_document,
    soft_delete_document,
    upload_document,
)
from apps.documents.storage import ControlledFileStorage
from apps.projects.models import ProjectMembership, ProjectRole, ProjectStatus

from .document_factories import make_document, make_file_asset
from .project_factories import make_project, make_user

pytestmark = pytest.mark.django_db

PDF_BYTES = b"%PDF-1.7\nlifecycle-evidence\n%%EOF\n"


@pytest.fixture
def lifecycle_context(tmp_path, settings):
    media_root = tmp_path / "media"
    settings.MEDIA_ROOT = media_root
    settings.LABARCHIVE_STAGING_ROOT = media_root / ".staging"
    pi = make_user("lifecycle-pi")
    member = make_user("lifecycle-member")
    manager = make_user("lifecycle-manager")
    viewer = make_user("lifecycle-viewer")
    project = make_project(pi=pi, code="DOCUMENT-LIFECYCLE")
    ProjectMembership.objects.create(project=project, user=member, role=ProjectRole.MEMBER)
    ProjectMembership.objects.create(project=project, user=manager, role=ProjectRole.MANAGER)
    ProjectMembership.objects.create(project=project, user=viewer, role=ProjectRole.VIEWER)
    category = project.document_categories.create(code="LIFECYCLE", name="生命周期")
    outcome = upload_document(
        actor=member,
        project=project,
        category=category,
        uploaded_file=SimpleUploadedFile(
            "生命周期.pdf",
            PDF_BYTES,
            content_type="application/pdf",
        ),
        upload_token=uuid4(),
        title="生命周期证据",
    )
    document = Document.all_objects.select_related("file_asset").get(pk=outcome.document.pk)
    return pi, member, manager, viewer, project, document, ControlledFileStorage()


def _system_admin(username):
    user = make_user(username)
    user.groups.add(Group.objects.get(name=SYSTEM_ADMIN_GROUP))
    user.groups.remove(Group.objects.get(name=LAB_MEMBER_GROUP))
    return user


def _reload(document):
    return Document.all_objects.select_related("file_asset", "project").get(pk=document.pk)


def test_member_soft_deletes_own_document_without_removing_physical_bytes(lifecycle_context):
    _, member, _, _, _, document, storage = lifecycle_context
    final_path = storage.resolve_final(document.file_asset.relative_path)

    deleted = soft_delete_document(actor=member, document=document)

    deleted = _reload(deleted)
    assert deleted.deleted_at is not None
    assert deleted.file_asset.storage_status == FileStorageStatus.DELETED
    assert deleted.file_asset.deleted_at == deleted.deleted_at
    assert final_path.read_bytes() == PDF_BYTES
    assert not Document.objects.filter(pk=deleted.pk).exists()
    assert (
        AuditLog.objects.filter(
            action=AuditAction.DOCUMENT_SOFT_DELETED,
            object_id=str(deleted.pk),
        ).count()
        == 1
    )


def test_delete_permission_matrix_and_archived_boundary(lifecycle_context):
    pi, member, manager, viewer, project, document, _ = lifecycle_context
    other = make_document(
        project=project,
        uploaded_by=pi,
        file_asset=make_file_asset(uploaded_by=pi),
    )

    with pytest.raises(PermissionDenied):
        soft_delete_document(actor=member, document=other)
    with pytest.raises(PermissionDenied):
        soft_delete_document(actor=viewer, document=document)

    manager_deleted = soft_delete_document(actor=manager, document=other)
    assert manager_deleted.deleted_at is not None

    project.status = ProjectStatus.ARCHIVED
    project.save(update_fields={"status", "updated_at"})
    with pytest.raises(PermissionDenied):
        soft_delete_document(actor=pi, document=document)


def test_system_admin_without_lab_member_can_delete_project_document(lifecycle_context):
    _, _, _, _, _, document, _ = lifecycle_context
    admin = _system_admin("lifecycle-system-admin")

    deleted = soft_delete_document(actor=admin, document=document)

    assert deleted.deleted_at is not None


def test_recycle_bin_is_limited_to_current_restore_scope(lifecycle_context):
    pi, member, manager, _, project, document, _ = lifecycle_context
    admin = _system_admin("lifecycle-bin-admin")
    soft_delete_document(actor=member, document=document)
    deleted = _reload(document)

    other_pi = make_user("lifecycle-other-pi")
    other_project = make_project(
        pi=other_pi,
        code="DOCUMENT-LIFECYCLE-OTHER",
        project_type=project.project_type,
    )
    other_deleted = make_document(
        project=other_project,
        uploaded_by=other_pi,
        deleted_at=deleted.deleted_at,
        file_asset=make_file_asset(
            uploaded_by=other_pi,
            status=FileStorageStatus.DELETED,
            deleted_at=deleted.deleted_at,
        ),
    )

    assert list(recycle_bin_documents_for(member)) == []
    assert list(recycle_bin_documents_for(pi)) == [document]
    assert list(recycle_bin_documents_for(manager)) == [document]
    assert {item.pk for item in recycle_bin_documents_for(admin)} == {
        document.pk,
        other_deleted.pk,
    }

    non_portal = make_user("lifecycle-bin-non-portal")
    non_portal.groups.remove(Group.objects.get(name=LAB_MEMBER_GROUP))
    with pytest.raises(PermissionDenied):
        list(recycle_bin_documents_for(non_portal))

    project.status = ProjectStatus.ARCHIVED
    project.save(update_fields={"status", "updated_at"})
    assert list(recycle_bin_documents_for(pi)) == []


def test_pi_restores_document_after_full_revalidation_but_member_cannot(lifecycle_context):
    pi, member, _, _, _, document, storage = lifecycle_context
    soft_delete_document(actor=member, document=document)
    deleted = _reload(document)

    with pytest.raises(PermissionDenied):
        restore_document(actor=member, document=deleted, storage=storage)

    restored = restore_document(actor=pi, document=deleted, storage=storage)

    restored = _reload(restored)
    assert restored.deleted_at is None
    assert restored.file_asset.storage_status == FileStorageStatus.AVAILABLE
    assert restored.file_asset.deleted_at is None
    assert storage.resolve_final(restored.file_asset.relative_path).read_bytes() == PDF_BYTES
    assert (
        AuditLog.objects.filter(
            action=AuditAction.DOCUMENT_RESTORED,
            object_id=str(restored.pk),
            result=AuditResult.SUCCESS,
        ).count()
        == 1
    )


def test_restore_missing_file_keeps_document_deleted_and_marks_asset_missing(lifecycle_context):
    pi, member, _, _, _, document, storage = lifecycle_context
    soft_delete_document(actor=member, document=document)
    storage.resolve_final(document.file_asset.relative_path).unlink()

    with pytest.raises(DocumentLifecycleError) as exc_info:
        restore_document(actor=pi, document=_reload(document), storage=storage)

    assert exc_info.value.code == "asset_missing"
    failed = _reload(document)
    assert failed.deleted_at is not None
    assert failed.file_asset.storage_status == FileStorageStatus.MISSING
    assert failed.file_asset.deleted_at is None
    assert AuditLog.objects.filter(action=AuditAction.FILE_MARKED_MISSING).count() == 1
    assert (
        AuditLog.objects.filter(
            action=AuditAction.DOCUMENT_RESTORED,
            result=AuditResult.FAILED,
        ).count()
        == 1
    )


def test_restore_same_size_tamper_fails_sha256_and_marks_missing(lifecycle_context):
    pi, member, _, _, _, document, storage = lifecycle_context
    soft_delete_document(actor=member, document=document)
    tampered = PDF_BYTES.replace(b"evidence", b"tampered")
    assert len(tampered) == len(PDF_BYTES)
    storage.resolve_final(document.file_asset.relative_path).write_bytes(tampered)

    with pytest.raises(DocumentLifecycleError) as exc_info:
        restore_document(actor=pi, document=_reload(document), storage=storage)

    assert exc_info.value.code == "sha256_mismatch"
    failed = _reload(document)
    assert failed.deleted_at is not None
    assert failed.file_asset.storage_status == FileStorageStatus.MISSING


def test_restore_scan_failure_quarantines_asset_and_retains_recycle_record(lifecycle_context):
    pi, member, _, _, _, document, storage = lifecycle_context
    soft_delete_document(actor=member, document=document)

    class InfectedScanner:
        def scan(self, path):
            assert path.read_bytes() == PDF_BYTES
            return ScanResult("INFECTED", "test_signature")

    with pytest.raises(DocumentLifecycleError) as exc_info:
        restore_document(
            actor=pi,
            document=_reload(document),
            storage=storage,
            scanner=InfectedScanner(),
        )

    assert exc_info.value.code == "scan_not_releasable"
    failed = _reload(document)
    assert failed.deleted_at is not None
    assert failed.file_asset.storage_status == FileStorageStatus.QUARANTINED
    assert failed.file_asset.deleted_at is None
    assert failed.file_asset.quarantined_at is not None


def test_restore_rechecks_project_state_after_file_validation(lifecycle_context):
    pi, member, _, _, project, document, storage = lifecycle_context
    soft_delete_document(actor=member, document=document)

    class ArchivingScanner:
        def scan(self, path):
            assert path.read_bytes() == PDF_BYTES
            type(project).all_objects.filter(pk=project.pk).update(status=ProjectStatus.ARCHIVED)
            return ScanResult("NOT_CONFIGURED", "scanner_not_configured")

    with pytest.raises(PermissionDenied):
        restore_document(
            actor=pi,
            document=_reload(document),
            storage=storage,
            scanner=ArchivingScanner(),
        )

    failed = _reload(document)
    assert failed.deleted_at is not None
    assert failed.file_asset.storage_status == FileStorageStatus.DELETED
    assert not any(settings_staging_files(storage))


def settings_staging_files(storage):
    if not storage.staging_root.exists():
        return []
    return storage.staging_root.iterdir()


def test_audit_failures_roll_back_delete_and_restore(lifecycle_context):
    pi, member, _, _, _, document, storage = lifecycle_context
    with patch(
        "apps.documents.services.record_audit_event",
        side_effect=RuntimeError("audit unavailable"),
    ):
        with pytest.raises(RuntimeError):
            soft_delete_document(actor=member, document=document)
    current = _reload(document)
    assert current.deleted_at is None
    assert current.file_asset.storage_status == FileStorageStatus.AVAILABLE

    soft_delete_document(actor=member, document=current)
    with patch(
        "apps.documents.services.record_audit_event",
        side_effect=RuntimeError("audit unavailable"),
    ):
        with pytest.raises(RuntimeError):
            restore_document(actor=pi, document=_reload(document), storage=storage)
    failed = _reload(document)
    assert failed.deleted_at is not None
    assert failed.file_asset.storage_status == FileStorageStatus.DELETED
    assert not any(settings_staging_files(storage))


def test_file_disappearing_after_validation_is_marked_missing(lifecycle_context):
    pi, member, _, _, _, document, storage = lifecycle_context
    soft_delete_document(actor=member, document=document)
    final_path = storage.resolve_final(document.file_asset.relative_path)

    class RemovingScanner:
        def scan(self, path):
            assert path.read_bytes() == PDF_BYTES
            final_path.unlink()
            return ScanResult("NOT_CONFIGURED", "scanner_not_configured")

    with pytest.raises(DocumentLifecycleError) as exc_info:
        restore_document(
            actor=pi,
            document=_reload(document),
            storage=storage,
            scanner=RemovingScanner(),
        )

    assert exc_info.value.code == "final_file_missing"
    assert _reload(document).file_asset.storage_status == FileStorageStatus.MISSING


def test_same_size_change_after_validation_is_marked_missing(lifecycle_context):
    pi, member, _, _, _, document, storage = lifecycle_context
    soft_delete_document(actor=member, document=document)
    final_path = storage.resolve_final(document.file_asset.relative_path)
    tampered = PDF_BYTES.replace(b"evidence", b"tampered")
    assert len(tampered) == len(PDF_BYTES)

    class ReplacingScanner:
        def scan(self, path):
            assert path.read_bytes() == PDF_BYTES
            final_path.write_bytes(tampered)
            return ScanResult("NOT_CONFIGURED", "scanner_not_configured")

    with pytest.raises(DocumentLifecycleError) as exc_info:
        restore_document(
            actor=pi,
            document=_reload(document),
            storage=storage,
            scanner=ReplacingScanner(),
        )

    assert exc_info.value.code == "final_file_changed"
    failed = _reload(document)
    assert failed.deleted_at is not None
    assert failed.file_asset.storage_status == FileStorageStatus.MISSING


def test_restore_rejects_current_version_conflict_after_validation(lifecycle_context):
    pi, member, _, _, project, document, storage = lifecycle_context
    soft_delete_document(actor=member, document=document)
    make_document(
        project=project,
        uploaded_by=pi,
        document_group_id=document.document_group_id,
        version=2,
        is_current=True,
        file_asset=make_file_asset(uploaded_by=pi),
    )

    with pytest.raises(DocumentLifecycleError) as exc_info:
        restore_document(actor=pi, document=_reload(document), storage=storage)

    assert exc_info.value.code == "current_version_conflict"
    failed = _reload(document)
    assert failed.deleted_at is not None
    assert failed.file_asset.storage_status == FileStorageStatus.DELETED
