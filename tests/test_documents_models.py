from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import AuditAction
from apps.documents.models import (
    Document,
    DocumentCategory,
    FileStorageStatus,
    MalwareScanStatus,
)

from .document_factories import make_document, make_file_asset
from .project_factories import make_project, make_user

pytestmark = pytest.mark.django_db


def test_temporary_asset_allows_incomplete_validation_metadata():
    user = make_user("asset-temporary-user")

    asset = make_file_asset(uploaded_by=user, status=FileStorageStatus.TEMPORARY)

    assert asset.file_size is None
    assert asset.sha256 == ""
    assert asset.detected_mime_type == ""
    assert asset.malware_scan_status == MalwareScanStatus.NOT_CONFIGURED


def test_available_asset_requires_complete_metadata_at_database_level():
    user = make_user("asset-complete-user")

    with pytest.raises(IntegrityError), transaction.atomic():
        make_file_asset(
            uploaded_by=user,
            status=FileStorageStatus.AVAILABLE,
            detected_mime_type="",
            file_size=None,
            sha256="",
        )


def test_quarantined_and_deleted_states_require_matching_timestamps():
    user = make_user("asset-state-shape-user")

    with pytest.raises(IntegrityError), transaction.atomic():
        make_file_asset(uploaded_by=user, status=FileStorageStatus.QUARANTINED)

    with pytest.raises(IntegrityError), transaction.atomic():
        make_file_asset(uploaded_by=user, status=FileStorageStatus.DELETED)

    quarantined = make_file_asset(
        uploaded_by=user,
        status=FileStorageStatus.QUARANTINED,
        quarantined_at=timezone.now(),
    )
    deleted = make_file_asset(
        uploaded_by=user,
        status=FileStorageStatus.DELETED,
        deleted_at=timezone.now(),
    )
    assert quarantined.quarantined_at is not None
    assert deleted.deleted_at is not None


def test_file_asset_storage_keys_and_upload_tokens_are_unique():
    user = make_user("asset-unique-user")
    asset = make_file_asset(uploaded_by=user)

    for field in ("stored_filename", "relative_path", "upload_token"):
        values = {field: getattr(asset, field)}
        with pytest.raises(IntegrityError), transaction.atomic():
            make_file_asset(uploaded_by=user, **values)


def test_sha256_database_constraint_rejects_invalid_value():
    user = make_user("asset-sha-user")

    with pytest.raises(IntegrityError), transaction.atomic():
        make_file_asset(uploaded_by=user, sha256="not-a-sha256")


@pytest.mark.parametrize(
    "unsafe_path",
    ["/absolute/file.pdf", "../escape.pdf", "projects\\escape.pdf", "C:/escape.pdf"],
)
def test_relative_storage_key_database_constraint_rejects_unsafe_shapes(unsafe_path):
    user = make_user(f"asset-path-{uuid4()}")

    with pytest.raises(IntegrityError), transaction.atomic():
        make_file_asset(uploaded_by=user, relative_path=unsafe_path)


def test_available_asset_rejects_pending_or_failed_scan_facts():
    user = make_user("asset-scan-shape-user")

    for scan_status in (
        MalwareScanStatus.PENDING,
        MalwareScanStatus.INFECTED,
        MalwareScanStatus.ERROR,
    ):
        with pytest.raises(IntegrityError), transaction.atomic():
            make_file_asset(uploaded_by=user, malware_scan_status=scan_status)


def test_global_and_project_category_uniqueness_is_case_insensitive_per_scope():
    pi = make_user("category-scope-pi")
    project = make_project(pi=pi)
    other_project = make_project(
        pi=pi,
        project_type=project.project_type,
        code="CATEGORY-OTHER",
    )
    DocumentCategory.objects.create(code="CONTRACT", name="合同")
    DocumentCategory.objects.create(project=project, code="CONTRACT", name="项目合同")
    DocumentCategory.objects.create(project=other_project, code="CONTRACT", name="项目合同")

    with pytest.raises(IntegrityError), transaction.atomic():
        DocumentCategory.objects.create(code="contract", name="其他全局名称")

    with pytest.raises(IntegrityError), transaction.atomic():
        DocumentCategory.objects.create(project=project, code="contract", name="其他项目名称")


def test_document_model_validation_rejects_cross_project_or_inactive_category():
    pi = make_user("document-validation-pi")
    project = make_project(pi=pi)
    other_project = make_project(
        pi=pi,
        project_type=project.project_type,
        code="DOCUMENT-VALIDATION-OTHER",
    )
    cross_project_category = DocumentCategory.objects.create(
        project=other_project,
        code="CROSS",
        name="其他项目分类",
    )
    inactive_category = DocumentCategory.objects.create(
        code="INACTIVE",
        name="停用分类",
        is_active=False,
    )

    cross_project_document = Document(
        project=project,
        category=cross_project_category,
        file_asset=make_file_asset(uploaded_by=pi),
        title="跨项目分类",
        uploaded_by=pi,
    )
    with pytest.raises(ValidationError, match="本项目分类"):
        cross_project_document.full_clean()

    inactive_document = Document(
        project=project,
        category=inactive_category,
        file_asset=make_file_asset(uploaded_by=pi),
        title="停用分类",
        uploaded_by=pi,
    )
    with pytest.raises(ValidationError, match="已停用分类"):
        inactive_document.full_clean()


def test_postgresql_trigger_rejects_cross_project_and_inactive_categories():
    pi = make_user("document-trigger-pi")
    project = make_project(pi=pi)
    other_project = make_project(
        pi=pi,
        project_type=project.project_type,
        code="DOCUMENT-TRIGGER-OTHER",
    )
    cross_project_category = DocumentCategory.objects.create(
        project=other_project,
        code="TRIGGER-CROSS",
        name="触发器跨项目分类",
    )
    inactive_category = DocumentCategory.objects.create(
        code="TRIGGER-INACTIVE",
        name="触发器停用分类",
        is_active=False,
    )

    for category in (cross_project_category, inactive_category):
        with pytest.raises(IntegrityError), transaction.atomic():
            make_document(project=project, uploaded_by=pi, category=category)


def test_postgresql_trigger_makes_category_scope_immutable():
    pi = make_user("category-immutable-pi")
    project = make_project(pi=pi)
    category = DocumentCategory.objects.create(code="IMMUTABLE", name="不可改范围")

    with pytest.raises(IntegrityError), transaction.atomic():
        DocumentCategory.objects.filter(pk=category.pk).update(project=project)


def test_document_version_constraints_and_active_manager():
    pi = make_user("document-version-pi")
    project = make_project(pi=pi)
    group_id = uuid4()
    document = make_document(project=project, uploaded_by=pi, document_group_id=group_id)

    with pytest.raises(IntegrityError), transaction.atomic():
        make_document(
            project=project,
            uploaded_by=pi,
            document_group_id=group_id,
            version=1,
            is_current=False,
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        make_document(
            project=project,
            uploaded_by=pi,
            document_group_id=group_id,
            version=2,
            is_current=True,
        )

    document.deleted_at = timezone.now()
    document.save(update_fields={"deleted_at", "updated_at"})
    assert not Document.objects.filter(pk=document.pk).exists()
    assert Document.all_objects.filter(pk=document.pk).exists()


def test_document_and_file_asset_are_one_to_one_and_keep_uploader_identity():
    uploader = make_user("document-owner")
    other = make_user("document-other")
    project = make_project(pi=uploader)
    asset = make_file_asset(uploaded_by=uploader)
    make_document(project=project, uploaded_by=uploader, file_asset=asset)

    with pytest.raises(IntegrityError), transaction.atomic():
        make_document(project=project, uploaded_by=uploader, file_asset=asset)

    mismatched = Document(
        project=project,
        category=DocumentCategory.objects.create(code="OWNER", name="上传者校验"),
        file_asset=make_file_asset(uploaded_by=uploader),
        title="上传者不一致",
        uploaded_by=other,
    )
    with pytest.raises(ValidationError, match="上传者"):
        mismatched.full_clean()


def test_phase_three_audit_actions_are_declared():
    assert {
        AuditAction.FILE_UPLOADED,
        AuditAction.FILE_UPLOAD_FAILED,
        AuditAction.FILE_DOWNLOADED,
        AuditAction.FILE_QUARANTINED,
        AuditAction.FILE_MARKED_MISSING,
        AuditAction.FILE_INTEGRITY_FAILED,
        AuditAction.DOCUMENT_SOFT_DELETED,
        AuditAction.DOCUMENT_RESTORED,
    } <= set(AuditAction.values)
