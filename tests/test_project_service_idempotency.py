import pytest
from django.core.exceptions import PermissionDenied

from apps.audit.models import AuditAction, AuditLog
from apps.projects.models import ProjectRole, ProjectVisibility
from apps.projects.services import (
    cancel_or_revoke_access_request,
    remove_project_member,
    review_access_request,
    set_project_member,
    submit_access_request,
)

from .project_factories import make_project, make_user

pytestmark = pytest.mark.django_db


def _audit_count(action, subject):
    return AuditLog.objects.filter(
        action=action,
        object_type=subject._meta.label,
        object_id=str(subject.pk),
    ).count()


def test_repeating_same_direct_role_assignment_is_a_no_op():
    pi = make_user("idempotent-set-pi")
    member = make_user("idempotent-set-member")
    project = make_project(pi=pi, code="IDEMPOTENT-SET")
    first = set_project_member(
        actor=pi,
        project=project,
        user=member,
        role=ProjectRole.MEMBER,
    )
    original_updated_at = first.updated_at
    original_added_audits = _audit_count(AuditAction.PROJECT_MEMBER_ADDED, first)
    original_updated_audits = _audit_count(AuditAction.PROJECT_MEMBER_UPDATED, first)
    assert original_added_audits == 1
    assert original_updated_audits == 0

    second = set_project_member(
        actor=pi,
        project=project,
        user=member,
        role=ProjectRole.MEMBER,
    )

    second.refresh_from_db()
    assert second.pk == first.pk
    assert second.updated_at == original_updated_at
    assert _audit_count(AuditAction.PROJECT_MEMBER_ADDED, second) == original_added_audits
    assert _audit_count(AuditAction.PROJECT_MEMBER_UPDATED, second) == original_updated_audits


def test_repeating_member_removal_returns_the_same_closed_row_without_new_audit():
    pi = make_user("idempotent-remove-pi")
    member = make_user("idempotent-remove-member")
    project = make_project(pi=pi, code="IDEMPOTENT-REMOVE")
    membership = set_project_member(
        actor=pi,
        project=project,
        user=member,
        role=ProjectRole.MEMBER,
    )
    first = remove_project_member(actor=pi, membership=membership)
    original_left_at = first.left_at
    original_updated_at = first.updated_at
    original_audits = _audit_count(AuditAction.PROJECT_MEMBER_REMOVED, first)
    assert original_audits == 1

    second = remove_project_member(actor=pi, membership=first)

    second.refresh_from_db()
    assert second.pk == first.pk
    assert second.left_at == original_left_at
    assert second.updated_at == original_updated_at
    assert _audit_count(AuditAction.PROJECT_MEMBER_REMOVED, second) == original_audits


def test_repeating_pending_request_cancellation_is_a_no_op():
    pi = make_user("idempotent-cancel-pi")
    requester = make_user("idempotent-cancel-requester")
    project = make_project(
        pi=pi,
        code="IDEMPOTENT-CANCEL",
        visibility=ProjectVisibility.RESTRICTED,
    )
    access_request = submit_access_request(
        actor=requester,
        project=project,
        reason="测试重复取消",
    )
    first = cancel_or_revoke_access_request(actor=requester, access_request=access_request)
    original_updated_at = first.updated_at
    original_audits = _audit_count(AuditAction.ACCESS_REQUEST_CANCELLED, first)
    assert original_audits == 1

    second = cancel_or_revoke_access_request(actor=requester, access_request=first)

    second.refresh_from_db()
    assert second.pk == first.pk
    assert second.updated_at == original_updated_at
    assert _audit_count(AuditAction.ACCESS_REQUEST_CANCELLED, second) == original_audits


def test_repeating_approved_request_revocation_is_a_no_op():
    pi = make_user("idempotent-revoke-pi")
    requester = make_user("idempotent-revoke-requester")
    project = make_project(
        pi=pi,
        code="IDEMPOTENT-REVOKE",
        visibility=ProjectVisibility.RESTRICTED,
    )
    access_request = submit_access_request(
        actor=requester,
        project=project,
        reason="测试重复撤销",
    )
    approved = review_access_request(
        actor=pi,
        access_request=access_request,
        approve=True,
    )
    membership = approved.granted_membership
    first = cancel_or_revoke_access_request(actor=pi, access_request=approved)
    membership.refresh_from_db()
    original_request_updated_at = first.updated_at
    original_membership_updated_at = membership.updated_at
    original_left_at = membership.left_at
    original_audits = _audit_count(AuditAction.ACCESS_REQUEST_REVOKED, first)
    assert original_audits == 1

    second = cancel_or_revoke_access_request(actor=pi, access_request=first)

    second.refresh_from_db()
    membership.refresh_from_db()
    assert second.pk == first.pk
    assert second.updated_at == original_request_updated_at
    assert membership.left_at == original_left_at
    assert membership.updated_at == original_membership_updated_at
    assert _audit_count(AuditAction.ACCESS_REQUEST_REVOKED, second) == original_audits


def test_unauthorized_terminal_request_retries_are_denied_before_idempotent_return():
    pi = make_user("terminal-auth-pi")
    requester = make_user("terminal-auth-requester")
    outsider = make_user("terminal-auth-outsider")
    project = make_project(
        pi=pi,
        code="TERMINAL-AUTH",
        visibility=ProjectVisibility.RESTRICTED,
    )
    pending = submit_access_request(
        actor=requester,
        project=project,
        reason="先由申请人取消",
    )
    cancelled = cancel_or_revoke_access_request(actor=requester, access_request=pending)
    cancelled_audits = _audit_count(AuditAction.ACCESS_REQUEST_CANCELLED, cancelled)

    with pytest.raises(PermissionDenied):
        cancel_or_revoke_access_request(actor=outsider, access_request=cancelled)

    assert _audit_count(AuditAction.ACCESS_REQUEST_CANCELLED, cancelled) == cancelled_audits

    second_request = submit_access_request(
        actor=requester,
        project=project,
        reason="再由负责人撤销",
    )
    approved = review_access_request(
        actor=pi,
        access_request=second_request,
        approve=True,
    )
    revoked = cancel_or_revoke_access_request(actor=pi, access_request=approved)
    revoked_audits = _audit_count(AuditAction.ACCESS_REQUEST_REVOKED, revoked)

    with pytest.raises(PermissionDenied):
        cancel_or_revoke_access_request(actor=outsider, access_request=revoked)

    assert _audit_count(AuditAction.ACCESS_REQUEST_REVOKED, revoked) == revoked_audits
