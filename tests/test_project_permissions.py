from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.utils import timezone

from apps.accounts.constants import (
    LAB_MEMBER_GROUP,
    REIMBURSEMENT_ADMIN_GROUP,
    SYSTEM_ADMIN_GROUP,
)
from apps.accounts.models import AccountStatus
from apps.projects.models import (
    MembershipAccessSource,
    ProjectMembership,
    ProjectRole,
    ProjectStatus,
    ProjectVisibility,
)
from apps.projects.permissions import (
    active_membership_for,
    can_manage_members,
    can_upload_project_files,
    can_view_project,
    editable_project_fields,
    is_active_lab_member,
    is_project_portal_user,
    viewable_projects_for,
)

from .project_factories import make_approved_access_request, make_project, make_user

pytestmark = pytest.mark.django_db


def test_internal_project_is_readable_by_every_active_member_but_not_editable():
    pi = make_user("internal-pi")
    member = make_user("internal-reader")
    project = make_project(pi=pi)

    assert can_view_project(member, project) is True
    assert editable_project_fields(member, project) == set()
    assert can_manage_members(member, project) is False
    assert can_upload_project_files(member, project) is False
    assert list(viewable_projects_for(member)) == [project]


def test_reimbursement_role_does_not_grant_restricted_project_access():
    pi = make_user("restricted-pi")
    reimbursement_admin = make_user("reimbursement-admin")
    reimbursement_admin.groups.add(Group.objects.get(name=REIMBURSEMENT_ADMIN_GROUP))
    project = make_project(pi=pi, visibility=ProjectVisibility.RESTRICTED)

    assert can_view_project(reimbursement_admin, project) is False
    assert not viewable_projects_for(reimbursement_admin).filter(pk=project.pk).exists()


def test_system_admin_and_all_project_roles_can_view_restricted_project():
    pi = make_user("roles-pi")
    system_admin = make_user("roles-system")
    system_admin.groups.add(Group.objects.get(name=SYSTEM_ADMIN_GROUP))
    project = make_project(pi=pi, visibility=ProjectVisibility.RESTRICTED)

    assert can_view_project(system_admin, project) is True
    for role in (ProjectRole.MANAGER, ProjectRole.MEMBER, ProjectRole.VIEWER):
        user = make_user(f"roles-{role.lower()}")
        ProjectMembership.objects.create(project=project, user=user, role=role)
        assert can_view_project(user, project) is True


def test_system_admin_without_lab_member_keeps_global_project_permissions():
    pi = make_user("global-admin-pi")
    system_admin = make_user("global-admin")
    system_admin.groups.add(Group.objects.get(name=SYSTEM_ADMIN_GROUP))
    system_admin.groups.remove(Group.objects.get(name=LAB_MEMBER_GROUP))
    project = make_project(pi=pi, visibility=ProjectVisibility.RESTRICTED)

    assert is_active_lab_member(system_admin) is False
    assert is_project_portal_user(system_admin) is True
    assert can_view_project(system_admin, project) is True
    assert editable_project_fields(system_admin, project)
    assert can_manage_members(system_admin, project) is True
    assert viewable_projects_for(system_admin).filter(pk=project.pk).exists()


def test_active_non_member_has_no_project_portal_or_project_visibility():
    pi = make_user("portal-denied-pi")
    non_member = make_user("portal-denied-user")
    non_member.groups.remove(Group.objects.get(name=LAB_MEMBER_GROUP))
    internal = make_project(pi=pi)
    restricted = make_project(
        pi=pi,
        project_type=internal.project_type,
        code="PORTAL-DENIED-RESTRICTED",
        visibility="RESTRICTED",
    )

    assert is_project_portal_user(non_member) is False
    assert list(viewable_projects_for(non_member)) == []
    assert can_view_project(non_member, internal) is False
    assert can_view_project(non_member, restricted) is False


def test_expired_or_inactive_membership_does_not_grant_access():
    pi = make_user("expired-pi")
    expired_user = make_user("expired-user")
    inactive_user = make_user("inactive-user")
    project = make_project(pi=pi, visibility=ProjectVisibility.RESTRICTED)
    now = timezone.now()
    access_request = make_approved_access_request(
        project=project,
        requester=expired_user,
        expires_at=now + timedelta(hours=1),
    )
    expired = ProjectMembership.objects.create(
        project=project,
        user=expired_user,
        role=ProjectRole.VIEWER,
        access_source=MembershipAccessSource.APPROVED_REQUEST,
        source_access_request=access_request,
        expires_at=now + timedelta(hours=1),
    )
    ProjectMembership.objects.filter(pk=expired.pk).update(
        joined_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
    )
    type(access_request).objects.filter(pk=access_request.pk).update(
        expires_at=now - timedelta(hours=1)
    )
    ProjectMembership.objects.create(
        project=project,
        user=inactive_user,
        role=ProjectRole.MEMBER,
    )
    inactive_user.account_status = AccountStatus.DEPARTED
    inactive_user.save(update_fields={"account_status", "updated_at"})

    assert can_view_project(expired_user, project, at=now) is False
    assert can_view_project(inactive_user, project, at=now) is False


def test_pi_permissions_fail_closed_when_canonical_and_membership_disagree():
    canonical_pi = make_user("canonical-pi")
    orphan_pi = make_user("orphan-pi")
    project = make_project(pi=canonical_pi, visibility=ProjectVisibility.RESTRICTED)
    canonical_membership = ProjectMembership.objects.get(project=project, user=canonical_pi)
    canonical_membership.left_at = timezone.now()
    canonical_membership.save(update_fields={"left_at", "updated_at"})
    ProjectMembership.objects.create(
        project=project,
        user=orphan_pi,
        role=ProjectRole.PI,
        access_source=MembershipAccessSource.DIRECT,
    )

    assert active_membership_for(canonical_pi, project) is None
    assert active_membership_for(orphan_pi, project) is None
    assert can_view_project(canonical_pi, project) is False
    assert can_view_project(orphan_pi, project) is False
    assert not viewable_projects_for(canonical_pi).filter(pk=project.pk).exists()
    assert not viewable_projects_for(orphan_pi).filter(pk=project.pk).exists()


def test_role_matrix_for_edit_member_management_and_future_upload():
    pi = make_user("matrix-pi")
    manager = make_user("matrix-manager")
    member = make_user("matrix-member")
    viewer = make_user("matrix-viewer")
    project = make_project(pi=pi, status=ProjectStatus.ACTIVE)
    for user, role in (
        (manager, ProjectRole.MANAGER),
        (member, ProjectRole.MEMBER),
        (viewer, ProjectRole.VIEWER),
    ):
        ProjectMembership.objects.create(project=project, user=user, role=role)

    assert "name" in editable_project_fields(pi, project)
    assert editable_project_fields(manager, project) == {
        "short_name",
        "status",
        "start_date",
        "end_date",
        "description",
    }
    assert editable_project_fields(member, project) == set()
    assert can_manage_members(pi, project) is True
    assert can_manage_members(manager, project) is True
    assert can_manage_members(member, project) is False
    assert can_upload_project_files(pi, project) is True
    assert can_upload_project_files(manager, project) is True
    assert can_upload_project_files(member, project) is True
    assert can_upload_project_files(viewer, project) is False
