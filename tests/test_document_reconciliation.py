import os
from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone

from apps.audit.models import AuditAction, AuditLog
from apps.documents.models import Document, DocumentCategory, FileAsset, FileStorageStatus
from apps.documents.reconciliation import ReconciliationReport, reconcile_document_storage
from apps.documents.services import upload_document
from apps.documents.storage import ControlledFileStorage

from .project_factories import make_project, make_user

pytestmark = pytest.mark.django_db

PDF_BYTES = b"%PDF-1.7\nreconciliation-evidence\n%%EOF\n"


@pytest.fixture
def reconciliation_context(tmp_path, settings):
    media_root = tmp_path / "media"
    settings.MEDIA_ROOT = media_root
    settings.LABARCHIVE_STAGING_ROOT = media_root / ".staging"
    actor = make_user("reconciliation-pi")
    project = make_project(pi=actor, code="RECONCILIATION")
    category = DocumentCategory.objects.create(code="RECON", name="核对")
    storage = ControlledFileStorage()
    outcome = upload_document(
        actor=actor,
        project=project,
        category=category,
        uploaded_file=SimpleUploadedFile(
            "核对.pdf",
            PDF_BYTES,
            content_type="application/pdf",
        ),
        upload_token=uuid4(),
        title="核对证据",
        storage=storage,
    )
    document = Document.all_objects.select_related("file_asset").get(pk=outcome.document.pk)
    return actor, project, document, storage


def _reload(document):
    return Document.all_objects.select_related("file_asset").get(pk=document.pk)


def _make_asset_stale(asset):
    stale_at = timezone.now() - timedelta(hours=2)
    FileAsset.objects.filter(pk=asset.pk).update(updated_at=stale_at)
    return stale_at


def _make_path_stale(path):
    stale_epoch = (timezone.now() - timedelta(hours=2)).timestamp()
    os.utime(path, (stale_epoch, stale_epoch))


def test_missing_available_file_is_marked_once_with_task_id(reconciliation_context):
    _, _, document, storage = reconciliation_context
    task_id = uuid4()
    storage.resolve_final(document.file_asset.relative_path).unlink()

    first = reconcile_document_storage(storage=storage, task_id=task_id)

    current = _reload(document)
    assert first.marked_missing == 1
    assert current.file_asset.storage_status == FileStorageStatus.MISSING
    audit = AuditLog.objects.get(
        action=AuditAction.FILE_MARKED_MISSING,
        object_id=str(document.pk),
    )
    assert audit.request_id == task_id
    assert audit.old_value == {"asset_status": FileStorageStatus.AVAILABLE}
    assert audit.new_value["asset_status"] == FileStorageStatus.MISSING

    second = reconcile_document_storage(storage=storage)
    assert second.marked_missing == 0
    assert AuditLog.objects.filter(action=AuditAction.FILE_MARKED_MISSING).count() == 1


def test_same_size_tamper_is_marked_missing_and_audited(reconciliation_context):
    _, _, document, storage = reconciliation_context
    final_path = storage.resolve_final(document.file_asset.relative_path)
    tampered = PDF_BYTES.replace(b"evidence", b"tampered")
    assert len(tampered) == len(PDF_BYTES)
    final_path.write_bytes(tampered)

    report = reconcile_document_storage(storage=storage)

    assert report.marked_missing == 1
    assert _reload(document).file_asset.storage_status == FileStorageStatus.MISSING
    assert AuditLog.objects.filter(action=AuditAction.FILE_INTEGRITY_FAILED).count() == 1


def test_valid_missing_asset_is_restored_after_full_revalidation(reconciliation_context):
    _, _, document, storage = reconciliation_context
    FileAsset.objects.filter(pk=document.file_asset_id).update(
        storage_status=FileStorageStatus.MISSING,
        status_reason="previous_transient_failure",
    )

    report = reconcile_document_storage(storage=storage)

    current = _reload(document)
    assert report.restored_missing == 1
    assert current.file_asset.storage_status == FileStorageStatus.AVAILABLE
    assert current.file_asset.status_reason == ""
    assert AuditLog.objects.filter(action=AuditAction.FILE_RECONCILED).count() == 1


@pytest.mark.parametrize("candidate_location", ["final", "staging"])
def test_stale_temporary_upload_is_resumed(reconciliation_context, candidate_location):
    _, _, document, storage = reconciliation_context
    asset = document.file_asset
    final_path = storage.resolve_final(asset.relative_path)
    if candidate_location == "staging":
        storage.ensure_roots()
        os.replace(final_path, storage.staging_path(asset.pk))
    FileAsset.objects.filter(pk=asset.pk).update(storage_status=FileStorageStatus.TEMPORARY)
    _make_asset_stale(asset)

    report = reconcile_document_storage(storage=storage)

    current = _reload(document)
    assert report.resumed_uploads == 1
    assert current.file_asset.storage_status == FileStorageStatus.AVAILABLE
    assert storage.resolve_final(asset.relative_path).read_bytes() == PDF_BYTES
    assert not storage.staging_path(asset.pk).exists()


def test_stale_temporary_without_bytes_is_quarantined(reconciliation_context):
    _, _, document, storage = reconciliation_context
    asset = document.file_asset
    storage.resolve_final(asset.relative_path).unlink()
    FileAsset.objects.filter(pk=asset.pk).update(storage_status=FileStorageStatus.TEMPORARY)
    _make_asset_stale(asset)

    report = reconcile_document_storage(storage=storage)

    assert report.quarantined_uploads == 1
    assert _reload(document).file_asset.storage_status == FileStorageStatus.QUARANTINED
    assert any("temporary_file_missing" in failure for failure in report.failures)


def test_stale_unowned_staging_is_audited_and_cleaned(reconciliation_context):
    _, _, _, storage = reconciliation_context
    staged = storage.stage_chunks(uuid4(), [b"stale-orphan"])
    _make_path_stale(staged.path)
    task_id = uuid4()

    report = reconcile_document_storage(storage=storage, task_id=task_id)

    assert report.cleaned_staging == 1
    assert not staged.path.exists()
    cleanup = AuditLog.objects.get(action=AuditAction.FILE_STAGING_CLEANED)
    assert cleanup.request_id == task_id
    assert cleanup.new_value == {"staging_name": staged.path.name}


def test_fresh_unowned_staging_is_preserved(reconciliation_context):
    _, _, _, storage = reconciliation_context
    staged = storage.stage_chunks(uuid4(), [b"active-attempt"])

    report = reconcile_document_storage(storage=storage)

    assert report.cleaned_staging == 0
    assert staged.path.read_bytes() == b"active-attempt"


def test_orphan_final_is_reported_and_never_deleted(reconciliation_context):
    _, _, _, storage = reconciliation_context
    orphan = storage.media_root / "projects" / "orphan" / "unknown.pdf"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(PDF_BYTES)
    task_id = uuid4()

    report = reconcile_document_storage(storage=storage, task_id=task_id)

    assert report.orphan_final_keys == ["projects/orphan/unknown.pdf"]
    assert orphan.read_bytes() == PDF_BYTES
    audit = AuditLog.objects.get(action=AuditAction.FILE_ORPHAN_DETECTED)
    assert audit.request_id == task_id
    assert audit.new_value["action"] == "reported_only"


def test_missing_transition_rolls_back_when_audit_fails(reconciliation_context):
    _, _, document, storage = reconciliation_context
    storage.resolve_final(document.file_asset.relative_path).unlink()

    with patch(
        "apps.documents.reconciliation.record_audit_event",
        side_effect=RuntimeError("audit unavailable"),
    ):
        with pytest.raises(RuntimeError, match="audit unavailable"):
            reconcile_document_storage(storage=storage)

    assert _reload(document).file_asset.storage_status == FileStorageStatus.AVAILABLE


def test_staging_cleanup_compensates_when_audit_fails(reconciliation_context):
    _, _, _, storage = reconciliation_context
    staged = storage.stage_chunks(uuid4(), [b"restore-on-audit-failure"])
    _make_path_stale(staged.path)

    with patch(
        "apps.documents.reconciliation.record_audit_event",
        side_effect=RuntimeError("audit unavailable"),
    ):
        report = reconcile_document_storage(storage=storage)

    assert report.cleaned_staging == 0
    assert any("RuntimeError" in failure for failure in report.failures)
    assert staged.path.read_bytes() == b"restore-on-audit-failure"


def test_production_reconciliation_without_real_scanner_fails_before_state_changes(
    reconciliation_context,
    settings,
):
    _, _, document, storage = reconciliation_context
    storage.resolve_final(document.file_asset.relative_path).unlink()
    settings.LABARCHIVE_REQUIRE_MALWARE_SCAN = True

    with pytest.raises(ValidationError, match="真实恶意软件扫描器"):
        reconcile_document_storage(storage=storage)

    assert _reload(document).file_asset.storage_status == FileStorageStatus.AVAILABLE


def test_command_uses_requested_task_id_and_prints_summary():
    task_id = uuid4()
    output = StringIO()
    report = ReconciliationReport(task_id=task_id, checked_assets=3, marked_missing=1)

    with patch(
        "apps.documents.management.commands.reconcile_document_storage.reconcile_document_storage",
        return_value=report,
    ) as reconcile:
        call_command(
            "reconcile_document_storage",
            stale_seconds=120,
            task_id=task_id,
            stdout=output,
            no_color=True,
        )

    reconcile.assert_called_once_with(stale_after=timedelta(seconds=120), task_id=task_id)
    assert f"Reconciliation task: {task_id}" in output.getvalue()
    assert "checked=3" in output.getvalue()
    assert "missing=1" in output.getvalue()
