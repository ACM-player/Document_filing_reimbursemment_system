from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.projects.models import (
    AccessRequestStatus,
    MembershipAccessSource,
    Project,
    ProjectAccessRequest,
    ProjectMembership,
    ProjectRole,
    ProjectType,
    ProjectVisibility,
)

PASSWORD = "Project-test-password-2026!"


def make_user(username, **kwargs):
    return get_user_model().objects.create_user(
        username=username,
        password=PASSWORD,
        **kwargs,
    )


def make_project_type(code="RESEARCH", name="科研项目", **kwargs):
    return ProjectType.objects.create(code=code, name=name, **kwargs)


def make_project(
    *,
    pi,
    project_type=None,
    code="PROJECT-001",
    name="示例项目",
    visibility=ProjectVisibility.INTERNAL,
    description="项目内部说明",
    **kwargs,
):
    project_type = project_type or make_project_type()
    project = Project.objects.create(
        project_code=code,
        name=name,
        project_type=project_type,
        visibility=visibility,
        principal_investigator=pi,
        created_by=pi,
        description=description,
        **kwargs,
    )
    ProjectMembership.objects.create(
        project=project,
        user=pi,
        role=ProjectRole.PI,
        access_source=MembershipAccessSource.DIRECT,
    )
    return project


def make_approved_access_request(
    *,
    project,
    requester,
    reviewer=None,
    expires_at=None,
    reason="测试访问申请",
):
    return ProjectAccessRequest.objects.create(
        project=project,
        requester=requester,
        reason=reason,
        status=AccessRequestStatus.APPROVED,
        reviewed_by=reviewer or project.principal_investigator,
        reviewed_at=timezone.now(),
        expires_at=expires_at,
    )
