from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group
from django.utils import timezone

from apps.accounts.constants import REIMBURSEMENT_ADMIN_GROUP, SYSTEM_ADMIN_GROUP
from apps.accounts.models import AccountStatus
from apps.documents.models import DocumentCategory, FileStorageStatus
from apps.documents.permissions import (
    can_download_document,
    can_edit_document,
    can_manage_global_document_categories,
    can_manage_project_document_categories,
    can_restore_document,
    can_soft_delete_document,
    can_upload_documents,
    can_view_document,
)
from apps.projects.models import ProjectMembership, ProjectRole, ProjectStatus, ProjectVisibility

from .document_factories import make_document, make_file_asset
from .project_factories import make_approved_access_request, make_project, make_user

pytestmark = pytest.mark.django_db


def _make_system_admin(username):
    user = make_user(username)
    user.groups.add(Group.objects.get(name=SYSTEM_ADMIN_GROUP))
    return user


def test_internal_reader_can_download_but_cannot_write_or_manage_categories():
    pi = make_user("document-internal-pi")
    reader = make_user("document-internal-reader")
    project = make_project(pi=pi)
    document = make_document(project=project, uploaded_by=pi)

    assert can_view_document(reader, document) is True
    assert can_download_document(reader, document) is True
    assert can_upload_documents(reader, project) is False
    assert can_edit_document(reader, document) is False
    assert can_soft_delete_document(reader, document) is False
    assert can_manage_project_document_categories(reader, project) is False


def test_restricted_project_roles_and_reimbursement_admin_boundary():
    pi = make_user("document-restricted-pi")
    manager = make_user("document-restricted-manager")
    member = make_user("document-restricted-member")
    viewer = make_user("document-restricted-viewer")
    outsider = make_user("document-restricted-outsider")
    reimbursement_admin = make_user("document-reimbursement-admin")
    reimbursement_admin.groups.add(Group.objects.get(name=REIMBURSEMENT_ADMIN_GROUP))
    project = make_project(pi=pi, visibility=ProjectVisibility.RESTRICTED)
    for user, role in (
        (manager, ProjectRole.MANAGER),
        (member, ProjectRole.MEMBER),
        (viewer, ProjectRole.VIEWER),
    ):
        ProjectMembership.objects.create(project=project, user=user, role=role)
    document = make_document(project=project, uploaded_by=member)

    for authorized in (pi, manager, member, viewer):
        assert can_download_document(authorized, document) is True
    for unauthorized in (outsider, reimbursement_admin):
        assert can_view_document(unauthorized, document) is False
        assert can_download_document(unauthorized, document) is False

    assert can_upload_documents(member, project) is True
    assert can_upload_documents(viewer, project) is False
    assert can_edit_document(member, document) is True
    assert can_edit_document(viewer, document) is False


def test_member_can_only_edit_and_delete_own_document():
    pi = make_user("document-owner-pi")
    member = make_user("document-owner-member")
    other_member = make_user("document-owner-other")
    project = make_project(pi=pi)
    for user in (member, other_member):
        ProjectMembership.objects.create(project=project, user=user, role=ProjectRole.MEMBER)
    own_document = make_document(project=project, uploaded_by=member)
    other_document = make_document(project=project, uploaded_by=other_member)

    assert can_edit_document(member, own_document) is True
    assert can_soft_delete_document(member, own_document) is True
    assert can_edit_document(member, other_document) is False
    assert can_soft_delete_document(member, other_document) is False


def test_pi_manager_and_system_admin_permissions_follow_category_and_restore_matrix():
    pi = make_user("document-matrix-pi")
    manager = make_user("document-matrix-manager")
    system_admin = _make_system_admin("document-matrix-admin")
    project = make_project(pi=pi)
    ProjectMembership.objects.create(project=project, user=manager, role=ProjectRole.MANAGER)
    document = make_document(
        project=project,
        uploaded_by=pi,
        deleted_at=timezone.now(),
        file_asset=make_file_asset(
            uploaded_by=pi,
            status=FileStorageStatus.DELETED,
            deleted_at=timezone.now(),
        ),
    )

    assert can_manage_global_document_categories(system_admin) is True
    assert can_manage_global_document_categories(pi) is False
    for actor in (system_admin, pi, manager):
        assert can_manage_project_document_categories(actor, project) is True
        assert can_restore_document(actor, document) is True


@pytest.mark.parametrize(
    "status",
    [
        ProjectStatus.PLANNING,
        ProjectStatus.ACTIVE,
        ProjectStatus.PAUSED,
        ProjectStatus.COMPLETED,
    ],
)
def test_non_archived_project_statuses_preserve_phase_two_upload_semantics(status):
    pi = make_user(f"document-status-{status.lower()}")
    project = make_project(pi=pi, status=status, code=f"DOCUMENT-{status}")

    assert can_upload_documents(pi, project) is True
    assert can_manage_project_document_categories(pi, project) is True


def test_archived_project_is_read_only_and_soft_deleted_project_denies_all_file_access():
    pi = make_user("document-project-state-pi")
    admin = _make_system_admin("document-project-state-admin")
    archived = make_project(pi=pi, status=ProjectStatus.ARCHIVED, code="DOCUMENT-ARCHIVED")
    archived_document = make_document(project=archived, uploaded_by=pi)

    for actor in (pi, admin):
        assert can_download_document(actor, archived_document) is True
        assert can_upload_documents(actor, archived) is False
        assert can_edit_document(actor, archived_document) is False
        assert can_manage_project_document_categories(actor, archived) is False

    deleted = make_project(
        pi=pi,
        project_type=archived.project_type,
        code="DOCUMENT-DELETED",
        deleted_at=timezone.now(),
    )
    deleted_document = make_document(project=deleted, uploaded_by=pi)
    for actor in (pi, admin):
        assert can_view_document(actor, deleted_document) is False
        assert can_download_document(actor, deleted_document) is False
        assert can_upload_documents(actor, deleted) is False


@pytest.mark.parametrize(
    "status",
    [
        FileStorageStatus.TEMPORARY,
        FileStorageStatus.QUARANTINED,
        FileStorageStatus.MISSING,
        FileStorageStatus.DELETED,
    ],
)
def test_only_available_assets_are_downloadable(status):
    pi = make_user(f"document-asset-{status.lower()}")
    project = make_project(pi=pi, code=f"ASSET-{status}")
    kwargs = {}
    if status == FileStorageStatus.QUARANTINED:
        kwargs["quarantined_at"] = timezone.now()
    if status == FileStorageStatus.DELETED:
        kwargs["deleted_at"] = timezone.now()
    asset = make_file_asset(uploaded_by=pi, status=status, **kwargs)
    document = make_document(project=project, uploaded_by=pi, file_asset=asset)

    assert can_view_document(pi, document) is True
    assert can_download_document(pi, document) is False


def test_expired_or_disabled_user_loses_restricted_document_access_immediately():
    pi = make_user("document-lifecycle-pi")
    viewer = make_user("document-lifecycle-viewer")
    project = make_project(
        pi=pi,
        code="DOCUMENT-LIFECYCLE",
        visibility=ProjectVisibility.RESTRICTED,
    )
    expires_at = timezone.now() + timedelta(days=1)
    source_request = make_approved_access_request(
        project=project,
        requester=viewer,
        expires_at=expires_at,
    )
    ProjectMembership.objects.create(
        project=project,
        user=viewer,
        role=ProjectRole.VIEWER,
        access_source="APPROVED_REQUEST",
        source_access_request=source_request,
        expires_at=expires_at,
    )
    document = make_document(project=project, uploaded_by=pi)
    assert can_download_document(viewer, document) is True

    with patch(
        "apps.projects.permissions.timezone.now",
        return_value=expires_at + timedelta(seconds=1),
    ):
        assert can_download_document(viewer, document) is False

    viewer.account_status = AccountStatus.DISABLED
    viewer.save(update_fields={"account_status", "updated_at"})
    assert can_download_document(viewer, document) is False


def test_inactive_category_does_not_change_historical_document_readability():
    pi = make_user("document-inactive-history-pi")
    project = make_project(pi=pi)
    category = DocumentCategory.objects.create(code="HISTORY", name="历史分类")
    document = make_document(project=project, uploaded_by=pi, category=category)
    category.is_active = False
    category.save(update_fields={"is_active", "updated_at"})

    assert can_download_document(pi, document) is True
