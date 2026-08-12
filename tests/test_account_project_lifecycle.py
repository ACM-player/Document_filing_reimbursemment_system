from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.constants import SYSTEM_ADMIN_GROUP
from apps.accounts.models import AccountStatus
from apps.accounts.services import change_user_status
from apps.audit.models import AuditAction, AuditLog
from apps.projects.models import (
    AccessRequestStatus,
    ProjectMembership,
    ProjectRole,
    ProjectStatus,
    ProjectVisibility,
)
from apps.projects.permissions import can_view_project
from apps.projects.services import (
    review_access_request,
    set_project_member,
    submit_access_request,
    update_project,
)

from .project_factories import make_project, make_project_type, make_user

pytestmark = pytest.mark.django_db


def _make_system_admin(username):
    user = make_user(username)
    user.groups.add(Group.objects.get(name=SYSTEM_ADMIN_GROUP))
    return user


def _make_restricted_projects(*, owner, prefix, count):
    project_type = make_project_type(code=f"{prefix}-TYPE", name=f"{prefix} 类型")
    return [
        make_project(
            pi=owner,
            project_type=project_type,
            code=f"{prefix}-{index}",
            visibility=ProjectVisibility.RESTRICTED,
        )
        for index in range(1, count + 1)
    ]


def test_disabling_user_preserves_project_state_and_reenable_restores_valid_access():
    admin_user = _make_system_admin("disable-lifecycle-admin")
    owner = make_user("disable-lifecycle-owner")
    target = make_user("disable-lifecycle-target")
    direct_project, approved_project, pending_project = _make_restricted_projects(
        owner=owner,
        prefix="DISABLE",
        count=3,
    )
    direct_membership = set_project_member(
        actor=owner,
        project=direct_project,
        user=target,
        role=ProjectRole.MEMBER,
    )
    approved_request = submit_access_request(
        actor=target,
        project=approved_project,
        reason="临时访问",
    )
    approved_request = review_access_request(
        actor=owner,
        access_request=approved_request,
        approve=True,
    )
    approved_membership = approved_request.granted_membership
    pending_request = submit_access_request(
        actor=target,
        project=pending_project,
        reason="待处理访问",
    )
    closure_audits_before = AuditLog.objects.filter(
        action__in=(
            AuditAction.PROJECT_MEMBER_REMOVED,
            AuditAction.ACCESS_REQUEST_CANCELLED,
            AuditAction.ACCESS_REQUEST_REVOKED,
        )
    ).count()

    disabled = change_user_status(
        user=target,
        new_status=AccountStatus.DISABLED,
        actor=admin_user,
    )

    direct_membership.refresh_from_db()
    approved_membership.refresh_from_db()
    approved_request.refresh_from_db()
    pending_request.refresh_from_db()
    assert disabled.account_status == AccountStatus.DISABLED
    assert disabled.is_active is False
    assert direct_membership.left_at is None
    assert approved_membership.left_at is None
    assert approved_request.status == AccessRequestStatus.APPROVED
    assert pending_request.status == AccessRequestStatus.PENDING
    assert can_view_project(disabled, direct_project) is False
    assert can_view_project(disabled, approved_project) is False
    assert (
        AuditLog.objects.filter(
            action__in=(
                AuditAction.PROJECT_MEMBER_REMOVED,
                AuditAction.ACCESS_REQUEST_CANCELLED,
                AuditAction.ACCESS_REQUEST_REVOKED,
            )
        ).count()
        == closure_audits_before
    )

    active = change_user_status(
        user=disabled,
        new_status=AccountStatus.ACTIVE,
        actor=admin_user,
    )

    direct_membership.refresh_from_db()
    approved_membership.refresh_from_db()
    assert active.is_active is True
    assert direct_membership.left_at is None
    assert approved_membership.left_at is None
    assert can_view_project(active, direct_project) is True
    assert can_view_project(active, approved_project) is True
    assert AuditLog.objects.filter(action=AuditAction.USER_STATUS_CHANGED).count() == 2


def test_reenabling_disabled_user_expires_elapsed_request_grant():
    admin_user = _make_system_admin("reenable-expiry-admin")
    owner = make_user("reenable-expiry-owner")
    target = make_user("reenable-expiry-target")
    (project,) = _make_restricted_projects(owner=owner, prefix="REENABLE", count=1)
    expires_at = timezone.now() + timedelta(days=1)
    access_request = submit_access_request(actor=target, project=project, reason="限时访问")
    access_request = review_access_request(
        actor=owner,
        access_request=access_request,
        approve=True,
        expires_at=expires_at,
    )
    membership = access_request.granted_membership
    disabled = change_user_status(
        user=target,
        new_status=AccountStatus.DISABLED,
        actor=admin_user,
    )

    with patch(
        "apps.projects.services.timezone.now", return_value=expires_at + timedelta(seconds=1)
    ):
        active = change_user_status(
            user=disabled,
            new_status=AccountStatus.ACTIVE,
            actor=admin_user,
        )

    access_request.refresh_from_db()
    membership.refresh_from_db()
    assert access_request.status == AccessRequestStatus.EXPIRED
    assert membership.left_at is not None
    assert can_view_project(active, project, at=expires_at + timedelta(seconds=1)) is False


def test_departing_user_ends_direct_and_request_access_without_rewriting_history():
    admin_user = _make_system_admin("departure-admin")
    owner = make_user("departure-owner")
    target = make_user("departure-target")
    direct_project, approved_project, pending_project = _make_restricted_projects(
        owner=owner,
        prefix="DEPARTURE",
        count=3,
    )
    direct_membership = set_project_member(
        actor=owner,
        project=direct_project,
        user=target,
        role=ProjectRole.MANAGER,
    )
    approved_request = submit_access_request(
        actor=target,
        project=approved_project,
        reason="批准后离组",
    )
    approved_request = review_access_request(
        actor=owner,
        access_request=approved_request,
        approve=True,
        review_note="批准记录保留",
    )
    original_reviewer_id = approved_request.reviewed_by_id
    original_reviewed_at = approved_request.reviewed_at
    approved_membership = approved_request.granted_membership
    pending_request = submit_access_request(
        actor=target,
        project=pending_project,
        reason="待处理后离组",
    )

    departed = change_user_status(
        user=target,
        new_status=AccountStatus.DEPARTED,
        actor=admin_user,
    )

    direct_membership.refresh_from_db()
    approved_membership.refresh_from_db()
    approved_request.refresh_from_db()
    pending_request.refresh_from_db()
    assert departed.account_status == AccountStatus.DEPARTED
    assert departed.is_active is False
    assert direct_membership.left_at is not None
    assert approved_membership.left_at is not None
    assert approved_membership.source_access_request == approved_request
    assert approved_request.status == AccessRequestStatus.CANCELLED
    assert approved_request.reviewed_by_id == original_reviewer_id
    assert approved_request.reviewed_at == original_reviewed_at
    assert pending_request.status == AccessRequestStatus.CANCELLED
    assert pending_request.reviewed_by_id is None
    assert pending_request.reviewed_at is None
    assert can_view_project(departed, direct_project) is False
    assert can_view_project(departed, approved_project) is False
    assert AuditLog.objects.filter(action=AuditAction.PROJECT_MEMBER_REMOVED).count() == 1
    assert AuditLog.objects.filter(action=AuditAction.ACCESS_REQUEST_REVOKED).count() == 1
    assert AuditLog.objects.filter(action=AuditAction.ACCESS_REQUEST_CANCELLED).count() == 1


def test_archiving_departed_user_is_idempotent_for_project_relations():
    admin_user = _make_system_admin("archive-lifecycle-admin")
    owner = make_user("archive-lifecycle-owner")
    target = make_user("archive-lifecycle-target")
    (project,) = _make_restricted_projects(owner=owner, prefix="ARCHIVE", count=1)
    membership = set_project_member(
        actor=owner,
        project=project,
        user=target,
        role=ProjectRole.MEMBER,
    )
    departed = change_user_status(
        user=target,
        new_status=AccountStatus.DEPARTED,
        actor=admin_user,
    )
    membership.refresh_from_db()
    original_left_at = membership.left_at
    closure_count = AuditLog.objects.filter(action=AuditAction.PROJECT_MEMBER_REMOVED).count()

    archived = change_user_status(
        user=departed,
        new_status=AccountStatus.ARCHIVED,
        actor=admin_user,
    )

    membership.refresh_from_db()
    assert archived.account_status == AccountStatus.ARCHIVED
    assert membership.left_at == original_left_at
    assert (
        AuditLog.objects.filter(action=AuditAction.PROJECT_MEMBER_REMOVED).count() == closure_count
    )
    assert AuditLog.objects.filter(action=AuditAction.USER_STATUS_CHANGED).count() == 2


@pytest.mark.parametrize(
    ("permanent_status", "forbidden_status"),
    [
        (AccountStatus.DEPARTED, AccountStatus.ACTIVE),
        (AccountStatus.DEPARTED, AccountStatus.DISABLED),
        (AccountStatus.ARCHIVED, AccountStatus.ACTIVE),
        (AccountStatus.ARCHIVED, AccountStatus.DISABLED),
    ],
)
def test_permanent_account_status_cannot_be_reactivated(
    permanent_status,
    forbidden_status,
):
    admin_user = _make_system_admin(f"permanent-admin-{permanent_status}-{forbidden_status}")
    target = make_user(f"permanent-target-{permanent_status}-{forbidden_status}")
    target = change_user_status(
        user=target,
        new_status=AccountStatus.DEPARTED,
        actor=admin_user,
    )
    if permanent_status == AccountStatus.ARCHIVED:
        target = change_user_status(
            user=target,
            new_status=AccountStatus.ARCHIVED,
            actor=admin_user,
        )
    audit_count = AuditLog.objects.filter(action=AuditAction.USER_STATUS_CHANGED).count()

    with pytest.raises(ValidationError):
        change_user_status(
            user=target,
            new_status=forbidden_status,
            actor=admin_user,
        )

    target.refresh_from_db()
    assert target.account_status == permanent_status
    assert AuditLog.objects.filter(action=AuditAction.USER_STATUS_CHANGED).count() == audit_count


def test_forced_low_level_reactivation_does_not_revive_departed_restricted_access():
    admin_user = _make_system_admin("forced-reactivation-admin")
    owner = make_user("forced-reactivation-owner")
    target = make_user("forced-reactivation-target")
    (project,) = _make_restricted_projects(owner=owner, prefix="FORCED", count=1)
    membership = set_project_member(
        actor=owner,
        project=project,
        user=target,
        role=ProjectRole.MEMBER,
    )
    departed = change_user_status(
        user=target,
        new_status=AccountStatus.DEPARTED,
        actor=admin_user,
    )

    departed.account_status = AccountStatus.ACTIVE
    departed.save(update_fields={"account_status", "updated_at"})

    membership.refresh_from_db()
    departed.refresh_from_db()
    assert membership.left_at is not None
    assert departed.is_active is True
    assert can_view_project(departed, project) is False


def test_pi_departure_is_blocked_until_project_is_transferred():
    admin_user = _make_system_admin("pi-departure-admin")
    departing_pi = make_user("departing-pi")
    new_pi = make_user("replacement-pi")
    project = make_project(
        pi=departing_pi,
        visibility=ProjectVisibility.RESTRICTED,
        code="PI-DEPARTURE",
    )

    with pytest.raises(ValidationError):
        change_user_status(
            user=departing_pi,
            new_status=AccountStatus.DEPARTED,
            actor=admin_user,
        )

    departing_pi.refresh_from_db()
    pi_membership = ProjectMembership.objects.get(project=project, user=departing_pi)
    assert departing_pi.account_status == AccountStatus.ACTIVE
    assert pi_membership.role == ProjectRole.PI
    assert pi_membership.left_at is None
    assert not AuditLog.objects.filter(action=AuditAction.USER_STATUS_CHANGED).exists()

    updated = update_project(
        actor=admin_user,
        project=project,
        cleaned_data={"principal_investigator": new_pi},
    )
    departed = change_user_status(
        user=departing_pi,
        new_status=AccountStatus.DEPARTED,
        actor=admin_user,
    )

    old_membership = ProjectMembership.objects.get(project=project, user=departing_pi)
    assert updated.principal_investigator == new_pi
    assert departed.account_status == AccountStatus.DEPARTED
    assert old_membership.role == ProjectRole.MANAGER
    assert old_membership.left_at is not None


def test_disabling_pi_preserves_canonical_membership():
    admin_user = _make_system_admin("disable-pi-admin")
    pi = make_user("disable-pi")
    project = make_project(
        pi=pi,
        visibility=ProjectVisibility.RESTRICTED,
        code="DISABLE-PI",
    )
    membership = ProjectMembership.objects.get(project=project, user=pi)

    disabled = change_user_status(
        user=pi,
        new_status=AccountStatus.DISABLED,
        actor=admin_user,
    )
    membership.refresh_from_db()
    project.refresh_from_db()
    assert project.principal_investigator == disabled
    assert membership.role == ProjectRole.PI
    assert membership.left_at is None
    assert can_view_project(disabled, project) is False

    active = change_user_status(
        user=disabled,
        new_status=AccountStatus.ACTIVE,
        actor=admin_user,
    )
    assert can_view_project(active, project) is True


def test_departure_rolls_back_all_relations_when_project_audit_fails():
    admin_user = _make_system_admin("rollback-departure-admin")
    owner = make_user("rollback-departure-owner")
    target = make_user("rollback-departure-target")
    (project,) = _make_restricted_projects(owner=owner, prefix="ROLLBACK", count=1)
    membership = set_project_member(
        actor=owner,
        project=project,
        user=target,
        role=ProjectRole.MEMBER,
    )

    with (
        patch(
            "apps.projects.services.record_audit_event",
            side_effect=RuntimeError("audit unavailable"),
        ),
        pytest.raises(RuntimeError, match="audit unavailable"),
    ):
        change_user_status(
            user=target,
            new_status=AccountStatus.DEPARTED,
            actor=admin_user,
        )

    target.refresh_from_db()
    membership.refresh_from_db()
    assert target.account_status == AccountStatus.ACTIVE
    assert target.is_active is True
    assert membership.left_at is None
    assert not AuditLog.objects.filter(action=AuditAction.USER_STATUS_CHANGED).exists()


def test_archived_project_pi_must_still_be_transferred_before_departure():
    admin_user = _make_system_admin("archived-pi-admin")
    pi = make_user("archived-project-pi")
    project = make_project(pi=pi, code="ARCHIVED-PI", status=ProjectStatus.ARCHIVED)

    with pytest.raises(ValidationError):
        change_user_status(
            user=pi,
            new_status=AccountStatus.DEPARTED,
            actor=admin_user,
        )

    project.refresh_from_db()
    pi.refresh_from_db()
    assert project.principal_investigator == pi
    assert pi.account_status == AccountStatus.ACTIVE
