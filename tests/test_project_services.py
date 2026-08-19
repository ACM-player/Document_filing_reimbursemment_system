from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.accounts.constants import SYSTEM_ADMIN_GROUP
from apps.audit.models import AuditAction, AuditLog
from apps.projects.models import (
    AccessRequestStatus,
    MembershipAccessSource,
    Project,
    ProjectMembership,
    ProjectRole,
    ProjectStatus,
    ProjectVisibility,
)
from apps.projects.permissions import can_view_project
from apps.projects.services import (
    cancel_or_revoke_access_request,
    create_project,
    expire_access_grants,
    remove_project_member,
    review_access_request,
    set_project_member,
    soft_delete_project,
    submit_access_request,
    update_project,
)

from .project_factories import make_project, make_project_type, make_user

pytestmark = pytest.mark.django_db


def _make_system_admin(username="project-system-admin"):
    user = make_user(username)
    user.groups.add(Group.objects.get(name=SYSTEM_ADMIN_GROUP))
    return user


def test_create_project_assigns_creator_as_pi_and_audits():
    creator = make_user("create-project-user")
    project_type = make_project_type()

    project = create_project(
        actor=creator,
        cleaned_data={
            "project_code": " CREATE-001 ",
            "name": " 新项目 ",
            "short_name": " 新项 ",
            "project_type": project_type,
            "status": ProjectStatus.PLANNING,
            "visibility": ProjectVisibility.INTERNAL,
            "start_date": None,
            "end_date": None,
            "description": "创建测试",
        },
    )

    membership = ProjectMembership.objects.get(project=project, user=creator)
    assert project.project_code == "CREATE-001"
    assert project.principal_investigator == creator
    assert membership.role == ProjectRole.PI
    assert AuditLog.objects.filter(action=AuditAction.PROJECT_CREATED).exists()


def test_pi_and_manager_update_boundaries_and_system_archive():
    pi = make_user("update-pi")
    manager = make_user("update-manager")
    member = make_user("update-member")
    system_admin = _make_system_admin("update-system")
    project = make_project(pi=pi)
    ProjectMembership.objects.create(project=project, user=manager, role=ProjectRole.MANAGER)
    ProjectMembership.objects.create(project=project, user=member, role=ProjectRole.MEMBER)

    updated = update_project(
        actor=pi,
        project=project,
        cleaned_data={"name": "负责人修改名称", "visibility": ProjectVisibility.RESTRICTED},
    )
    assert updated.name == "负责人修改名称"
    assert updated.visibility == ProjectVisibility.RESTRICTED

    updated = update_project(
        actor=manager,
        project=updated,
        cleaned_data={"description": "管理员修改说明", "status": ProjectStatus.ACTIVE},
    )
    assert updated.description == "管理员修改说明"
    with pytest.raises(PermissionDenied):
        update_project(
            actor=manager,
            project=updated,
            cleaned_data={"name": "越权名称"},
        )
    with pytest.raises(PermissionDenied):
        update_project(
            actor=member,
            project=updated,
            cleaned_data={"description": "成员越权"},
        )
    with pytest.raises(PermissionDenied):
        update_project(
            actor=pi,
            project=updated,
            cleaned_data={"status": ProjectStatus.ARCHIVED},
        )

    archived = update_project(
        actor=system_admin,
        project=updated,
        cleaned_data={"status": ProjectStatus.ARCHIVED},
    )
    assert archived.status == ProjectStatus.ARCHIVED
    assert AuditLog.objects.filter(action=AuditAction.PROJECT_ARCHIVED).exists()


def test_system_admin_transfers_pi_without_losing_old_pi_membership():
    old_pi = make_user("transfer-old-pi")
    new_pi = make_user("transfer-new-pi")
    system_admin = _make_system_admin("transfer-system")
    project = make_project(pi=old_pi)

    updated = update_project(
        actor=system_admin,
        project=project,
        cleaned_data={"principal_investigator": new_pi},
    )

    assert updated.principal_investigator == new_pi
    assert ProjectMembership.objects.get(project=project, user=new_pi).role == ProjectRole.PI
    assert ProjectMembership.objects.get(project=project, user=old_pi).role == ProjectRole.MANAGER
    assert AuditLog.objects.filter(action=AuditAction.PROJECT_PI_TRANSFERRED).exists()


def test_project_managers_can_set_and_remove_non_pi_members():
    pi = make_user("members-pi")
    manager = make_user("members-manager")
    target = make_user("members-target")
    project = make_project(pi=pi)
    ProjectMembership.objects.create(project=project, user=manager, role=ProjectRole.MANAGER)

    membership = set_project_member(
        actor=manager,
        project=project,
        user=target,
        role=ProjectRole.MEMBER,
    )
    assert membership.role == ProjectRole.MEMBER
    membership = set_project_member(
        actor=manager,
        project=project,
        user=target,
        role=ProjectRole.VIEWER,
    )
    assert membership.role == ProjectRole.VIEWER

    removed = remove_project_member(actor=manager, membership=membership)
    assert removed.left_at is not None
    with pytest.raises(ValidationError):
        remove_project_member(
            actor=manager,
            membership=ProjectMembership.objects.get(project=project, user=pi),
        )


def test_restricted_access_approval_creates_expiring_viewer_and_expiry_revokes_it():
    pi = make_user("access-pi")
    requester = make_user("access-requester")
    project = make_project(pi=pi, visibility=ProjectVisibility.RESTRICTED)
    access_request = submit_access_request(
        actor=requester,
        project=project,
        reason="需要整理项目材料",
    )
    expires_at = timezone.now() + timedelta(days=2)

    approved = review_access_request(
        actor=pi,
        access_request=access_request,
        approve=True,
        review_note="同意临时访问",
        expires_at=expires_at,
    )

    membership = ProjectMembership.objects.get(project=project, user=requester)
    assert approved.status == AccessRequestStatus.APPROVED
    assert membership.role == ProjectRole.VIEWER
    assert membership.access_source == MembershipAccessSource.APPROVED_REQUEST
    assert membership.source_access_request == approved
    assert approved.granted_membership == membership
    assert membership.expires_at == approved.expires_at == expires_at
    assert can_view_project(requester, project) is True

    assert expire_access_grants(at=expires_at + timedelta(seconds=1)) == 1
    approved.refresh_from_db()
    membership.refresh_from_db()
    assert approved.status == AccessRequestStatus.EXPIRED
    assert membership.left_at is not None
    assert can_view_project(requester, project, at=expires_at + timedelta(seconds=1)) is False
    assert AuditLog.objects.filter(action=AuditAction.ACCESS_REQUEST_EXPIRED).exists()
    assert expire_access_grants(at=expires_at + timedelta(seconds=2)) == 0


def test_direct_assignment_cancels_pending_request_and_stale_approval_fails():
    pi = make_user("no-downgrade-pi")
    requester = make_user("no-downgrade-requester")
    project = make_project(pi=pi, visibility=ProjectVisibility.RESTRICTED)
    access_request = submit_access_request(
        actor=requester,
        project=project,
        reason="申请后被直接加入",
    )
    membership = set_project_member(
        actor=pi,
        project=project,
        user=requester,
        role=ProjectRole.MEMBER,
    )

    access_request.refresh_from_db()
    with pytest.raises(ValidationError):
        review_access_request(
            actor=pi,
            access_request=access_request,
            approve=True,
            expires_at=timezone.now() + timedelta(days=1),
        )

    membership.refresh_from_db()
    assert access_request.status == AccessRequestStatus.CANCELLED
    assert membership.role == ProjectRole.MEMBER
    assert membership.access_source == MembershipAccessSource.DIRECT
    assert membership.source_access_request is None
    assert membership.expires_at is None
    assert not ProjectMembership.objects.filter(source_access_request=access_request).exists()


def test_rejection_requires_note_and_pending_requester_can_cancel():
    pi = make_user("reject-pi")
    requester = make_user("reject-requester")
    project = make_project(pi=pi, visibility=ProjectVisibility.RESTRICTED)
    access_request = submit_access_request(actor=requester, project=project, reason="申请访问")

    with pytest.raises(ValidationError):
        review_access_request(
            actor=pi,
            access_request=access_request,
            approve=False,
            review_note="",
        )
    cancelled = cancel_or_revoke_access_request(
        actor=requester,
        access_request=access_request,
    )
    assert cancelled.status == AccessRequestStatus.CANCELLED
    assert AuditLog.objects.filter(action=AuditAction.ACCESS_REQUEST_CANCELLED).exists()


def test_approved_request_revocation_closes_its_exact_grant():
    pi = make_user("revoke-pi")
    requester = make_user("revoke-requester")
    project = make_project(pi=pi, visibility=ProjectVisibility.RESTRICTED)
    access_request = submit_access_request(actor=requester, project=project, reason="临时访问")
    approved = review_access_request(
        actor=pi,
        access_request=access_request,
        approve=True,
    )

    revoked = cancel_or_revoke_access_request(actor=pi, access_request=approved)
    membership = ProjectMembership.objects.get(project=project, user=requester)
    assert revoked.status == AccessRequestStatus.CANCELLED
    assert membership.source_access_request == approved
    assert membership.left_at is not None
    assert AuditLog.objects.filter(action=AuditAction.ACCESS_REQUEST_REVOKED).exists()


def test_removing_request_viewer_revokes_its_source_request():
    pi = make_user("remove-request-viewer-pi")
    requester = make_user("remove-request-viewer")
    project = make_project(pi=pi, visibility=ProjectVisibility.RESTRICTED)
    access_request = submit_access_request(
        actor=requester,
        project=project,
        reason="先审批后从成员页移除",
    )
    approved = review_access_request(
        actor=pi,
        access_request=access_request,
        approve=True,
    )
    request_grant = approved.granted_membership

    removed = remove_project_member(actor=pi, membership=request_grant)

    approved.refresh_from_db()
    request_grant.refresh_from_db()
    assert removed.pk == request_grant.pk
    assert request_grant.left_at is not None
    assert request_grant.source_access_request == approved
    assert approved.status == AccessRequestStatus.CANCELLED
    assert can_view_project(requester, project) is False
    revoke_event = AuditLog.objects.get(
        action=AuditAction.ACCESS_REQUEST_REVOKED,
        object_id=str(approved.pk),
    )
    assert revoke_event.new_value == {
        "status": AccessRequestStatus.CANCELLED,
        "reason": "removed_from_project_members",
    }


def test_revoking_old_approved_request_does_not_close_newer_grant():
    pi = make_user("multi-revoke-pi")
    requester = make_user("multi-revoke-requester")
    project = make_project(pi=pi, visibility=ProjectVisibility.RESTRICTED)
    first_request = submit_access_request(actor=requester, project=project, reason="第一轮申请")
    first_request = review_access_request(
        actor=pi,
        access_request=first_request,
        approve=True,
    )
    first_grant = first_request.granted_membership
    first_grant.left_at = timezone.now()
    first_grant.save(update_fields={"left_at", "updated_at"})

    second_request = submit_access_request(actor=requester, project=project, reason="第二轮申请")
    second_request = review_access_request(
        actor=pi,
        access_request=second_request,
        approve=True,
    )
    second_grant = second_request.granted_membership

    cancel_or_revoke_access_request(actor=pi, access_request=first_request)

    first_request.refresh_from_db()
    first_grant.refresh_from_db()
    second_request.refresh_from_db()
    second_grant.refresh_from_db()
    assert first_request.status == AccessRequestStatus.CANCELLED
    assert first_grant.left_at is not None
    assert second_request.status == AccessRequestStatus.APPROVED
    assert second_grant.left_at is None
    assert second_grant.source_access_request == second_request
    assert can_view_project(requester, project) is True


def test_expiring_old_approved_request_does_not_close_newer_grant():
    pi = make_user("multi-expiry-pi")
    requester = make_user("multi-expiry-requester")
    project = make_project(
        pi=pi,
        visibility=ProjectVisibility.RESTRICTED,
        code="MULTI-EXPIRY",
    )
    expires_at = timezone.now() + timedelta(days=1)
    first_request = submit_access_request(actor=requester, project=project, reason="第一轮限时申请")
    first_request = review_access_request(
        actor=pi,
        access_request=first_request,
        approve=True,
        expires_at=expires_at,
    )
    first_grant = first_request.granted_membership
    first_grant.left_at = timezone.now()
    first_grant.save(update_fields={"left_at", "updated_at"})

    second_request = submit_access_request(
        actor=requester, project=project, reason="第二轮长期申请"
    )
    second_request = review_access_request(
        actor=pi,
        access_request=second_request,
        approve=True,
    )
    second_grant = second_request.granted_membership

    assert expire_access_grants(at=expires_at + timedelta(seconds=1)) == 1

    first_request.refresh_from_db()
    first_grant.refresh_from_db()
    second_request.refresh_from_db()
    second_grant.refresh_from_db()
    assert first_request.status == AccessRequestStatus.EXPIRED
    assert first_grant.left_at is not None
    assert second_request.status == AccessRequestStatus.APPROVED
    assert second_grant.left_at is None
    assert can_view_project(requester, project) is True


def test_direct_promotion_preserves_request_grant_history():
    pi = make_user("promotion-pi")
    requester = make_user("promotion-requester")
    project = make_project(pi=pi, visibility=ProjectVisibility.RESTRICTED)
    access_request = submit_access_request(actor=requester, project=project, reason="先临时查看")
    approved = review_access_request(
        actor=pi,
        access_request=access_request,
        approve=True,
        expires_at=timezone.now() + timedelta(days=1),
    )
    request_grant = approved.granted_membership

    direct_membership = set_project_member(
        actor=pi,
        project=project,
        user=requester,
        role=ProjectRole.MEMBER,
    )

    approved.refresh_from_db()
    request_grant.refresh_from_db()
    assert approved.status == AccessRequestStatus.CANCELLED
    assert request_grant.left_at is not None
    assert request_grant.role == ProjectRole.VIEWER
    assert request_grant.access_source == MembershipAccessSource.APPROVED_REQUEST
    assert request_grant.source_access_request == approved
    assert direct_membership.pk != request_grant.pk
    assert direct_membership.role == ProjectRole.MEMBER
    assert direct_membership.access_source == MembershipAccessSource.DIRECT
    assert direct_membership.source_access_request is None
    assert direct_membership.expires_at is None
    assert can_view_project(requester, project) is True


def test_pi_transfer_preserves_request_grant_lineage():
    old_pi = make_user("lineage-old-pi")
    new_pi = make_user("lineage-new-pi")
    system_admin = _make_system_admin("lineage-system-admin")
    project = make_project(
        pi=old_pi,
        visibility=ProjectVisibility.RESTRICTED,
        code="LINEAGE-PI",
    )
    access_request = submit_access_request(actor=new_pi, project=project, reason="临时查看")
    approved = review_access_request(
        actor=old_pi,
        access_request=access_request,
        approve=True,
        expires_at=timezone.now() + timedelta(days=1),
    )
    request_grant = approved.granted_membership

    updated = update_project(
        actor=system_admin,
        project=project,
        cleaned_data={"principal_investigator": new_pi},
    )

    approved.refresh_from_db()
    request_grant.refresh_from_db()
    active_pi = ProjectMembership.objects.get(
        project=project,
        user=new_pi,
        left_at__isnull=True,
    )
    assert updated.principal_investigator == new_pi
    assert approved.status == AccessRequestStatus.CANCELLED
    assert request_grant.left_at is not None
    assert request_grant.source_access_request == approved
    assert active_pi.pk != request_grant.pk
    assert active_pi.role == ProjectRole.PI
    assert active_pi.access_source == MembershipAccessSource.DIRECT
    assert active_pi.source_access_request is None
    assert active_pi.expires_at is None


def test_only_system_admin_can_soft_delete_project():
    pi = make_user("delete-pi")
    system_admin = _make_system_admin("delete-system")
    project = make_project(pi=pi)

    with pytest.raises(PermissionDenied):
        soft_delete_project(actor=pi, project=project)
    deleted = soft_delete_project(actor=system_admin, project=project)

    assert deleted.deleted_at is not None
    assert not Project.objects.filter(pk=project.pk).exists()
    assert AuditLog.objects.filter(action=AuditAction.PROJECT_SOFT_DELETED).exists()
