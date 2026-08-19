from datetime import date, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from apps.projects.models import (
    AccessRequestStatus,
    MembershipAccessSource,
    Project,
    ProjectAccessRequest,
    ProjectMembership,
    ProjectRole,
    ProjectType,
)

from .project_factories import (
    make_approved_access_request,
    make_project,
    make_project_type,
    make_user,
)

pytestmark = pytest.mark.django_db


def test_project_type_normalizes_code_and_active_name_is_case_insensitively_unique():
    first = make_project_type(code=" research ", name=" 科研项目 ")

    assert first.code == "RESEARCH"
    assert first.name == "科研项目"
    with pytest.raises(IntegrityError), transaction.atomic():
        ProjectType.objects.create(code="OTHER", name="科研项目")


def test_project_date_order_is_enforced_by_database_constraint():
    pi = make_user("date-pi")
    project_type = make_project_type()

    with pytest.raises(IntegrityError), transaction.atomic():
        Project.objects.create(
            project_code="INVALID-DATES",
            name="日期错误项目",
            project_type=project_type,
            principal_investigator=pi,
            created_by=pi,
            start_date=date(2026, 8, 10),
            end_date=date(2026, 8, 9),
        )


def test_only_one_active_membership_per_user_and_one_active_pi_per_project():
    pi = make_user("constraint-pi")
    other = make_user("constraint-other")
    project = make_project(pi=pi)

    with pytest.raises(IntegrityError), transaction.atomic():
        ProjectMembership.objects.create(
            project=project,
            user=pi,
            role=ProjectRole.MEMBER,
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        ProjectMembership.objects.create(
            project=project,
            user=other,
            role=ProjectRole.PI,
        )


def test_only_one_pending_request_per_user_and_project():
    pi = make_user("pending-pi")
    requester = make_user("pending-requester")
    project = make_project(pi=pi)
    ProjectAccessRequest.objects.create(
        project=project,
        requester=requester,
        reason="首次申请",
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        ProjectAccessRequest.objects.create(
            project=project,
            requester=requester,
            reason="重复申请",
        )


def test_rejected_request_requires_note_at_database_layer():
    pi = make_user("reject-constraint-pi")
    requester = make_user("reject-constraint-requester")
    project = make_project(pi=pi)

    with pytest.raises(IntegrityError), transaction.atomic():
        ProjectAccessRequest.objects.create(
            project=project,
            requester=requester,
            reason="申请访问",
            status=AccessRequestStatus.REJECTED,
            reviewed_by=pi,
            reviewed_at=timezone.now(),
            review_note="",
        )


def test_soft_deleted_projects_are_hidden_from_default_manager():
    pi = make_user("deleted-pi")
    project = make_project(pi=pi)
    project.deleted_at = timezone.now()
    project.save(update_fields={"deleted_at", "updated_at"})

    assert not Project.objects.filter(pk=project.pk).exists()
    assert Project.all_objects.filter(pk=project.pk).exists()


@pytest.mark.parametrize(
    ("role", "access_source", "with_request", "with_expiry"),
    [
        (ProjectRole.MEMBER, MembershipAccessSource.DIRECT, False, True),
        (ProjectRole.VIEWER, MembershipAccessSource.DIRECT, True, False),
        (ProjectRole.VIEWER, MembershipAccessSource.APPROVED_REQUEST, False, True),
        (ProjectRole.MEMBER, MembershipAccessSource.APPROVED_REQUEST, True, True),
        (ProjectRole.PI, MembershipAccessSource.APPROVED_REQUEST, True, True),
    ],
)
def test_membership_grant_shape_is_enforced_by_database(
    role,
    access_source,
    with_request,
    with_expiry,
):
    pi = make_user(f"shape-pi-{role}-{access_source}-{with_request}-{with_expiry}")
    target = (
        pi
        if role == ProjectRole.PI
        else make_user(f"shape-target-{role}-{access_source}-{with_request}-{with_expiry}")
    )
    project_type = make_project_type(
        code=f"TYPE-{role}-{access_source}-{with_request}-{with_expiry}",
        name=f"类型-{role}-{access_source}-{with_request}-{with_expiry}",
    )
    project = Project.objects.create(
        project_code=f"SHAPE-{role}-{access_source}-{with_request}-{with_expiry}",
        name="授权形状约束项目",
        project_type=project_type,
        principal_investigator=pi,
        created_by=pi,
    )
    expires_at = timezone.now() + timedelta(days=1) if with_expiry else None
    access_request = None
    if with_request:
        access_request = make_approved_access_request(
            project=project,
            requester=target,
            expires_at=expires_at,
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        ProjectMembership.objects.create(
            project=project,
            user=target,
            role=role,
            access_source=access_source,
            source_access_request=access_request,
            expires_at=expires_at,
        )


def test_permanent_request_viewer_and_direct_viewer_are_valid_grant_shapes():
    pi = make_user("valid-shape-pi")
    request_viewer = make_user("valid-request-viewer")
    direct_viewer = make_user("valid-direct-viewer")
    project = make_project(pi=pi)
    access_request = make_approved_access_request(
        project=project,
        requester=request_viewer,
    )

    request_membership = ProjectMembership.objects.create(
        project=project,
        user=request_viewer,
        role=ProjectRole.VIEWER,
        access_source=MembershipAccessSource.APPROVED_REQUEST,
        source_access_request=access_request,
    )
    direct_membership = ProjectMembership.objects.create(
        project=project,
        user=direct_viewer,
        role=ProjectRole.VIEWER,
        access_source=MembershipAccessSource.DIRECT,
    )

    assert request_membership.source_access_request == access_request
    assert access_request.granted_membership == request_membership
    assert direct_membership.source_access_request is None


def test_one_request_cannot_source_two_membership_history_rows_and_is_protected():
    pi = make_user("one-to-one-pi")
    requester = make_user("one-to-one-requester")
    project = make_project(pi=pi)
    access_request = make_approved_access_request(project=project, requester=requester)
    first = ProjectMembership.objects.create(
        project=project,
        user=requester,
        role=ProjectRole.VIEWER,
        access_source=MembershipAccessSource.APPROVED_REQUEST,
        source_access_request=access_request,
    )
    first.left_at = timezone.now()
    first.save(update_fields={"left_at", "updated_at"})

    with pytest.raises(IntegrityError), transaction.atomic():
        ProjectMembership.objects.create(
            project=project,
            user=requester,
            role=ProjectRole.VIEWER,
            access_source=MembershipAccessSource.APPROVED_REQUEST,
            source_access_request=access_request,
        )
    with pytest.raises(ProtectedError):
        access_request.delete()


def test_membership_model_validation_rejects_cross_project_or_user_request_links():
    pi = make_user("cross-link-pi")
    requester = make_user("cross-link-requester")
    other = make_user("cross-link-other")
    project = make_project(pi=pi, code="CROSS-ONE")
    other_project = make_project(
        pi=pi,
        project_type=project.project_type,
        code="CROSS-TWO",
    )
    access_request = make_approved_access_request(project=project, requester=requester)

    wrong_project = ProjectMembership(
        project=other_project,
        user=requester,
        role=ProjectRole.VIEWER,
        access_source=MembershipAccessSource.APPROVED_REQUEST,
        source_access_request=access_request,
    )
    wrong_user = ProjectMembership(
        project=project,
        user=other,
        role=ProjectRole.VIEWER,
        access_source=MembershipAccessSource.APPROVED_REQUEST,
        source_access_request=access_request,
    )

    with pytest.raises(ValidationError):
        wrong_project.full_clean()
    with pytest.raises(ValidationError):
        wrong_user.full_clean()
