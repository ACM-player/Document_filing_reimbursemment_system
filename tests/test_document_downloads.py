from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.constants import (
    LAB_MEMBER_GROUP,
    REIMBURSEMENT_ADMIN_GROUP,
    SYSTEM_ADMIN_GROUP,
)
from apps.audit.models import AuditAction, AuditLog
from apps.documents.models import FileAsset, FileStorageStatus
from apps.documents.services import (
    DocumentDownloadError,
    PreparedDownload,
    prepare_document_download,
    upload_document,
)
from apps.documents.storage import ControlledFileStorage
from apps.projects.models import (
    MembershipAccessSource,
    ProjectMembership,
    ProjectRole,
    ProjectStatus,
    ProjectVisibility,
)

from .document_factories import make_document, make_file_asset
from .project_factories import make_approved_access_request, make_project, make_user

pytestmark = pytest.mark.django_db(transaction=True)

PDF_BYTES = b"%PDF-1.7\ndownload-evidence\n%%EOF\n"


@pytest.fixture
def download_context(tmp_path, settings):
    media_root = tmp_path / "media"
    settings.MEDIA_ROOT = media_root
    settings.LABARCHIVE_STAGING_ROOT = media_root / ".staging"
    actor = make_user("download-pi")
    project = make_project(pi=actor, code="DOWNLOAD-PROJECT")
    category = project.document_categories.create(code="DOWNLOAD", name="下载资料")
    outcome = upload_document(
        actor=actor,
        project=project,
        category=category,
        uploaded_file=SimpleUploadedFile(
            "中文 证据.pdf",
            PDF_BYTES,
            content_type="application/pdf",
        ),
        upload_token=uuid4(),
        title="下载证据",
    )
    document = (
        type(outcome.document).all_objects.select_related("file_asset").get(pk=outcome.document.pk)
    )
    return actor, project, document, ControlledFileStorage()


def _download_body(response):
    return b"".join(response.streaming_content)


def test_download_service_opens_available_file_and_records_start_audit(download_context):
    actor, _, document, storage = download_context

    prepared = prepare_document_download(
        actor=actor,
        document_id=document.pk,
        storage=storage,
    )
    try:
        assert prepared.file.read() == PDF_BYTES
        assert prepared.filename == "中文 证据.pdf"
        assert prepared.content_type == "application/pdf"
        assert prepared.file_size == len(PDF_BYTES)
    finally:
        prepared.file.close()
    assert (
        AuditLog.objects.filter(
            action=AuditAction.FILE_DOWNLOADED,
            object_id=str(document.pk),
            result="SUCCESS",
        ).count()
        == 1
    )


def test_missing_physical_file_transitions_asset_before_safe_failure(download_context):
    actor, _, document, storage = download_context
    storage.resolve_final(document.file_asset.relative_path).unlink()

    with pytest.raises(DocumentDownloadError) as exc_info:
        prepare_document_download(actor=actor, document_id=document.pk, storage=storage)

    assert exc_info.value.code == "asset_missing"
    asset = FileAsset.objects.get(pk=document.file_asset_id)
    assert asset.storage_status == FileStorageStatus.MISSING
    assert asset.status_reason == "final_file_missing"
    assert AuditLog.objects.filter(action=AuditAction.FILE_MARKED_MISSING).count() == 1


def test_size_anomaly_rehashes_then_marks_integrity_failure(download_context):
    actor, _, document, storage = download_context
    storage.resolve_final(document.file_asset.relative_path).write_bytes(PDF_BYTES + b"tampered")

    with pytest.raises(DocumentDownloadError) as exc_info:
        prepare_document_download(actor=actor, document_id=document.pk, storage=storage)

    assert exc_info.value.code == "integrity_failed"
    asset = FileAsset.objects.get(pk=document.file_asset_id)
    assert asset.storage_status == FileStorageStatus.MISSING
    integrity_audit = AuditLog.objects.get(action=AuditAction.FILE_INTEGRITY_FAILED)
    assert integrity_audit.old_value["sha256"] == document.file_asset.sha256
    assert integrity_audit.new_value["file_size"] == len(PDF_BYTES) + len(b"tampered")


def test_same_size_tamper_is_never_served_and_marks_integrity_failure(download_context):
    actor, _, document, storage = download_context
    tampered = PDF_BYTES.replace(b"evidence", b"tampered")
    assert len(tampered) == len(PDF_BYTES)
    storage.resolve_final(document.file_asset.relative_path).write_bytes(tampered)

    with pytest.raises(DocumentDownloadError) as exc_info:
        prepare_document_download(actor=actor, document_id=document.pk, storage=storage)

    assert exc_info.value.code == "integrity_failed"
    asset = FileAsset.objects.get(pk=document.file_asset_id)
    assert asset.storage_status == FileStorageStatus.MISSING
    integrity_audit = AuditLog.objects.get(action=AuditAction.FILE_INTEGRITY_FAILED)
    assert integrity_audit.old_value["sha256"] == document.file_asset.sha256
    assert integrity_audit.new_value["file_size"] == len(PDF_BYTES)
    assert integrity_audit.new_value["sha256"] != document.file_asset.sha256
    assert not AuditLog.objects.filter(
        action=AuditAction.FILE_DOWNLOADED,
        result="SUCCESS",
    ).exists()


def test_symlinked_final_file_is_never_served(download_context, tmp_path):
    actor, _, document, storage = download_context
    final_path = storage.resolve_final(document.file_asset.relative_path)
    final_path.unlink()
    other = tmp_path / "media" / "other.pdf"
    other.write_bytes(PDF_BYTES)
    final_path.symlink_to(other)

    with pytest.raises(DocumentDownloadError) as exc_info:
        prepare_document_download(actor=actor, document_id=document.pk, storage=storage)

    assert exc_info.value.code == "asset_missing"
    assert (
        FileAsset.objects.get(pk=document.file_asset_id).storage_status == FileStorageStatus.MISSING
    )


def test_download_endpoint_requires_login_and_only_accepts_get(download_context):
    actor, _, document, _ = download_context
    url = reverse("documents:download", args=(document.pk,))
    anonymous = Client()
    assert anonymous.get(url).status_code == 302

    client = Client()
    client.force_login(actor)
    response = client.post(url)
    assert response.status_code == 405
    assert AuditLog.objects.filter(action=AuditAction.FILE_DOWNLOADED).count() == 0


def test_non_portal_account_is_rejected_before_document_lookup(download_context):
    _, _, document, _ = download_context
    non_portal = make_user("download-non-portal")
    non_portal.groups.remove(Group.objects.get(name=LAB_MEMBER_GROUP))
    client = Client()
    client.force_login(non_portal)

    assert client.get(reverse("documents:download", args=(document.pk,))).status_code == 403
    assert client.get(reverse("documents:download", args=(uuid4(),))).status_code == 403
    assert AuditLog.objects.filter(action=AuditAction.FILE_DOWNLOADED).count() == 0


def test_internal_reader_gets_real_bytes_and_safe_chinese_disposition(download_context):
    _, _, document, _ = download_context
    reader = make_user("download-internal-reader")
    client = Client()
    client.force_login(reader)

    response = client.get(reverse("documents:download", args=(document.pk,)))

    assert response.status_code == 200
    assert _download_body(response) == PDF_BYTES
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Length"] == str(len(PDF_BYTES))
    disposition = response["Content-Disposition"]
    assert disposition.startswith("attachment;")
    assert "filename*=utf-8''" in disposition
    assert document.file_asset.relative_path not in disposition


def test_restricted_download_matrix_and_direct_uuid_idor_are_enforced(tmp_path, settings):
    media_root = tmp_path / "restricted-media"
    settings.MEDIA_ROOT = media_root
    settings.LABARCHIVE_STAGING_ROOT = media_root / ".staging"
    pi = make_user("download-restricted-pi")
    member = make_user("download-restricted-member")
    viewer = make_user("download-restricted-viewer")
    outsider = make_user("download-restricted-outsider")
    reimbursement_admin = make_user("download-reimbursement-admin")
    reimbursement_admin.groups.add(Group.objects.get(name=REIMBURSEMENT_ADMIN_GROUP))
    system_admin = make_user("download-system-admin")
    system_admin.groups.add(Group.objects.get(name=SYSTEM_ADMIN_GROUP))
    system_admin.groups.remove(Group.objects.get(name=LAB_MEMBER_GROUP))
    project = make_project(
        pi=pi,
        code="DOWNLOAD-RESTRICTED",
        visibility=ProjectVisibility.RESTRICTED,
    )
    ProjectMembership.objects.create(project=project, user=member, role=ProjectRole.MEMBER)
    viewer_expiry = timezone.now() + timedelta(days=1)
    source_request = make_approved_access_request(
        project=project,
        requester=viewer,
        expires_at=viewer_expiry,
    )
    viewer_membership = ProjectMembership.objects.create(
        project=project,
        user=viewer,
        role=ProjectRole.VIEWER,
        access_source=MembershipAccessSource.APPROVED_REQUEST,
        source_access_request=source_request,
        expires_at=viewer_expiry,
    )
    category = project.document_categories.create(code="PRIVATE", name="受限资料")
    outcome = upload_document(
        actor=pi,
        project=project,
        category=category,
        uploaded_file=SimpleUploadedFile("private.pdf", PDF_BYTES, content_type="application/pdf"),
        upload_token=uuid4(),
        title="受限文件",
    )
    url = reverse("documents:download", args=(outcome.document.pk,))

    for user in (pi, member, viewer, system_admin):
        client = Client()
        client.force_login(user)
        response = client.get(url)
        assert response.status_code == 200
        assert _download_body(response) == PDF_BYTES
    for user in (outsider, reimbursement_admin):
        client = Client()
        client.force_login(user)
        assert client.get(url).status_code == 404
    client = Client()
    client.force_login(outsider)
    assert client.get(reverse("documents:download", args=(uuid4(),))).status_code == 404

    expired_at = timezone.now() - timedelta(seconds=1)
    ProjectMembership.objects.filter(pk=viewer_membership.pk).update(
        joined_at=expired_at - timedelta(minutes=1),
        expires_at=expired_at,
    )
    expired_viewer_client = Client()
    expired_viewer_client.force_login(viewer)
    assert expired_viewer_client.get(url).status_code == 404


def test_archived_is_readable_but_soft_deleted_document_and_unavailable_asset_fail_closed(
    download_context,
):
    actor, project, document, _ = download_context
    project.status = ProjectStatus.ARCHIVED
    project.save(update_fields={"status", "updated_at"})
    client = Client()
    client.force_login(actor)
    url = reverse("documents:download", args=(document.pk,))
    response = client.get(url)
    assert response.status_code == 200
    assert _download_body(response) == PDF_BYTES

    document.deleted_at = timezone.now()
    document.save(update_fields={"deleted_at", "updated_at"})
    assert client.get(url).status_code == 404

    unavailable = make_document(
        project=project,
        uploaded_by=actor,
        file_asset=make_file_asset(
            uploaded_by=actor,
            status=FileStorageStatus.QUARANTINED,
            quarantined_at=timezone.now(),
        ),
    )
    assert client.get(reverse("documents:download", args=(unavailable.pk,))).status_code == 404


def test_download_audit_failure_prevents_response_and_keeps_asset_available(download_context):
    actor, _, document, storage = download_context

    with patch(
        "apps.documents.services.record_audit_event",
        side_effect=RuntimeError("audit unavailable"),
    ):
        with pytest.raises(RuntimeError):
            prepare_document_download(actor=actor, document_id=document.pk, storage=storage)

    assert FileAsset.objects.get(pk=document.file_asset_id).storage_status == (
        FileStorageStatus.AVAILABLE
    )


def test_download_closes_open_file_when_database_commit_fails():
    opened_file = BytesIO(PDF_BYTES)
    decision = SimpleNamespace(
        prepared=PreparedDownload(
            document=None,
            file=opened_file,
            filename="commit-failure.pdf",
            content_type="application/pdf",
            file_size=len(PDF_BYTES),
        ),
        error=None,
    )

    class CommitFailure:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            if exc_type is None:
                raise RuntimeError("database commit failed")
            return False

    with (
        patch("apps.documents.services.transaction.atomic", return_value=CommitFailure()),
        patch("apps.documents.services._prepare_document_download", return_value=decision),
        pytest.raises(RuntimeError, match="database commit failed"),
    ):
        prepare_document_download(actor=object(), document_id=uuid4(), storage=object())

    assert opened_file.closed
