import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.accounts.constants import LAB_MEMBER_GROUP
from apps.accounts.models import AccountStatus
from apps.audit.models import AuditAction, AuditLog
from apps.projects.models import (
    AccessRequestStatus,
    Project,
    ProjectMembership,
    ProjectStatus,
    ProjectVisibility,
)
from apps.projects.services import (
    create_project,
    review_access_request,
    submit_access_request,
    update_project,
)

from .project_factories import make_project, make_project_type, make_user

pytestmark = pytest.mark.django_db

REVIEW_REJECTION_ERRORS = (PermissionDenied, ValidationError)


def _project_create_data(*, project_type, code, status=ProjectStatus.PLANNING):
    return {
        "project_code": code,
        "name": f"{code} 项目",
        "short_name": code,
        "project_type": project_type,
        "status": status,
        "visibility": ProjectVisibility.RESTRICTED,
        "start_date": None,
        "end_date": None,
        "description": "服务边界测试",
    }


def _assert_request_still_pending_without_grant(access_request):
    access_request.refresh_from_db()
    assert access_request.status == AccessRequestStatus.PENDING
    assert access_request.reviewed_by is None
    assert access_request.reviewed_at is None
    assert access_request.expires_at is None
    assert not ProjectMembership.objects.filter(source_access_request=access_request).exists()
    assert not AuditLog.objects.filter(
        action=AuditAction.ACCESS_REQUEST_APPROVED,
        object_id=str(access_request.pk),
    ).exists()


def test_create_project_rejects_archived_status_even_for_system_admin():
    system_admin = make_user("boundary-create-archived-admin", is_superuser=True, is_staff=True)
    project_type = make_project_type(code="BOUNDARY-ARCHIVED", name="归档创建边界")

    with pytest.raises(ValidationError):
        create_project(
            actor=system_admin,
            cleaned_data=_project_create_data(
                project_type=project_type,
                code="BOUNDARY-CREATE-ARCHIVED",
                status=ProjectStatus.ARCHIVED,
            ),
        )

    assert not Project.all_objects.filter(project_code="BOUNDARY-CREATE-ARCHIVED").exists()
    assert not AuditLog.objects.filter(action=AuditAction.PROJECT_CREATED).exists()


def test_create_project_rejects_inactive_type_even_for_system_admin():
    system_admin = make_user("boundary-create-type-admin", is_superuser=True, is_staff=True)
    inactive_type = make_project_type(
        code="BOUNDARY-INACTIVE-CREATE",
        name="停用创建类型",
        is_active=False,
    )

    with pytest.raises(ValidationError):
        create_project(
            actor=system_admin,
            cleaned_data=_project_create_data(
                project_type=inactive_type,
                code="BOUNDARY-CREATE-INACTIVE",
            ),
        )

    assert not Project.all_objects.filter(project_code="BOUNDARY-CREATE-INACTIVE").exists()
    assert not AuditLog.objects.filter(action=AuditAction.PROJECT_CREATED).exists()


def test_update_project_rejects_switch_to_inactive_type_without_changing_project():
    pi = make_user("boundary-update-type-pi")
    current_type = make_project_type(code="BOUNDARY-CURRENT", name="当前项目类型")
    inactive_type = make_project_type(
        code="BOUNDARY-INACTIVE-TARGET",
        name="停用目标类型",
        is_active=False,
    )
    project = make_project(
        pi=pi,
        project_type=current_type,
        code="BOUNDARY-UPDATE-INACTIVE",
    )

    with pytest.raises(ValidationError):
        update_project(
            actor=pi,
            project=project,
            cleaned_data={"project_type": inactive_type},
        )

    project.refresh_from_db()
    assert project.project_type == current_type
    assert not AuditLog.objects.filter(
        action=AuditAction.PROJECT_UPDATED,
        object_id=str(project.pk),
    ).exists()


def test_update_project_allows_retaining_its_current_type_after_type_is_disabled():
    pi = make_user("boundary-retain-type-pi")
    current_type = make_project_type(code="BOUNDARY-RETAIN", name="保留当前类型")
    project = make_project(
        pi=pi,
        project_type=current_type,
        code="BOUNDARY-RETAIN-INACTIVE",
    )
    current_type.is_active = False
    current_type.save(update_fields={"is_active", "updated_at"})

    updated = update_project(
        actor=pi,
        project=project,
        cleaned_data={
            "project_type": current_type,
            "description": "类型停用后仍可保留当前选择",
        },
    )

    assert updated.project_type == current_type
    assert updated.description == "类型停用后仍可保留当前选择"


@pytest.mark.parametrize("invalid_status", [AccountStatus.DISABLED, AccountStatus.DEPARTED])
def test_review_rejects_requester_who_became_inactive_after_submission(invalid_status):
    pi = make_user(f"boundary-review-{invalid_status.lower()}-pi")
    requester = make_user(f"boundary-review-{invalid_status.lower()}-requester")
    project = make_project(
        pi=pi,
        code=f"BOUNDARY-{invalid_status}",
        visibility=ProjectVisibility.RESTRICTED,
    )
    access_request = submit_access_request(
        actor=requester,
        project=project,
        reason="状态变化前提交",
    )
    requester.account_status = invalid_status
    requester.save(update_fields={"account_status", "updated_at"})

    with pytest.raises(REVIEW_REJECTION_ERRORS):
        review_access_request(
            actor=pi,
            access_request=access_request,
            approve=True,
        )

    _assert_request_still_pending_without_grant(access_request)


def test_review_rejects_requester_removed_from_lab_member_group_after_submission():
    pi = make_user("boundary-review-role-pi")
    requester = make_user("boundary-review-role-requester")
    project = make_project(
        pi=pi,
        code="BOUNDARY-REQUESTER-ROLE",
        visibility=ProjectVisibility.RESTRICTED,
    )
    access_request = submit_access_request(
        actor=requester,
        project=project,
        reason="移出成员组前提交",
    )
    requester.groups.remove(Group.objects.get(name=LAB_MEMBER_GROUP))

    with pytest.raises(REVIEW_REJECTION_ERRORS):
        review_access_request(
            actor=pi,
            access_request=access_request,
            approve=True,
        )

    _assert_request_still_pending_without_grant(access_request)


@pytest.mark.parametrize("project_change", ["archived", "soft_deleted", "internal"])
def test_review_rejects_project_that_became_ineligible_after_submission(project_change):
    pi = make_user(f"boundary-review-project-{project_change}-pi")
    requester = make_user(f"boundary-review-project-{project_change}-requester")
    project = make_project(
        pi=pi,
        code=f"BOUNDARY-PROJECT-{project_change.upper()}",
        visibility=ProjectVisibility.RESTRICTED,
    )
    access_request = submit_access_request(
        actor=requester,
        project=project,
        reason="项目状态变化前提交",
    )
    if project_change == "archived":
        project.status = ProjectStatus.ARCHIVED
        project.save(update_fields={"status", "updated_at"})
    elif project_change == "soft_deleted":
        project.deleted_at = timezone.now()
        project.save(update_fields={"deleted_at", "updated_at"})
    else:
        project.visibility = ProjectVisibility.INTERNAL
        project.save(update_fields={"visibility", "updated_at"})

    with pytest.raises(REVIEW_REJECTION_ERRORS):
        review_access_request(
            actor=pi,
            access_request=access_request,
            approve=True,
        )

    _assert_request_still_pending_without_grant(access_request)
