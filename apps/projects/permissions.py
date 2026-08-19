from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from apps.accounts.constants import LAB_MEMBER_GROUP, SYSTEM_ADMIN_GROUP

from .models import Project, ProjectMembership, ProjectRole, ProjectStatus, ProjectVisibility

PI_EDITABLE_FIELDS = {
    "project_code",
    "name",
    "short_name",
    "project_type",
    "status",
    "visibility",
    "start_date",
    "end_date",
    "description",
}
MANAGER_EDITABLE_FIELDS = {
    "short_name",
    "status",
    "start_date",
    "end_date",
    "description",
}
SYSTEM_ADMIN_EDITABLE_FIELDS = PI_EDITABLE_FIELDS | {"principal_investigator"}


def is_active_lab_member(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and user.is_active
        and (user.is_superuser or user.groups.filter(name=LAB_MEMBER_GROUP).exists())
    )


def is_system_admin(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and user.is_active
        and (user.is_superuser or user.groups.filter(name=SYSTEM_ADMIN_GROUP).exists())
    )


def is_project_portal_user(user) -> bool:
    """Return whether an active account may enter the project portal.

    LAB_MEMBER remains the normal project-participation role.  A system
    administrator is an intentionally separate emergency/global-management
    role and must not lose the portal merely because its LAB_MEMBER group was
    removed.
    """
    return is_active_lab_member(user) or is_system_admin(user)


def valid_memberships(*, at=None):
    current_time = at or timezone.now()
    return ProjectMembership.objects.filter(
        left_at__isnull=True,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=current_time))


def active_membership_for(user, project, *, at=None):
    if not is_active_lab_member(user):
        return None
    membership = valid_memberships(at=at).filter(project=project, user=user).first()
    if membership is None:
        return None
    is_canonical_pi = project.principal_investigator_id == user.pk
    if (membership.role == ProjectRole.PI) != is_canonical_pi:
        return None
    return membership


def catalog_projects_for(user):
    if not is_project_portal_user(user):
        return Project.objects.none()
    return Project.objects.select_related("project_type", "principal_investigator")


def viewable_projects_for(user, *, at=None):
    if not is_project_portal_user(user):
        return Project.objects.none()
    projects = Project.objects.select_related("project_type", "principal_investigator")
    if is_system_admin(user):
        return projects
    current_time = at or timezone.now()
    effective_memberships = (
        valid_memberships(at=current_time)
        .filter(project=OuterRef("pk"), user=user)
        .filter(
            Q(role=ProjectRole.PI, project__principal_investigator=user)
            | (~Q(role=ProjectRole.PI) & ~Q(project__principal_investigator=user))
        )
    )
    return projects.alias(has_effective_membership=Exists(effective_memberships)).filter(
        Q(visibility=ProjectVisibility.INTERNAL) | Q(has_effective_membership=True)
    )


def can_view_project(user, project, *, at=None) -> bool:
    if not is_project_portal_user(user) or project.deleted_at is not None:
        return False
    if is_system_admin(user) or project.visibility == ProjectVisibility.INTERNAL:
        return True
    return active_membership_for(user, project, at=at) is not None


def project_role_for(user, project, *, at=None):
    membership = active_membership_for(user, project, at=at)
    return membership.role if membership is not None else None


def editable_project_fields(user, project) -> set[str]:
    if not is_project_portal_user(user) or project.deleted_at is not None:
        return set()
    if is_system_admin(user):
        return set(SYSTEM_ADMIN_EDITABLE_FIELDS)
    if project.status == ProjectStatus.ARCHIVED:
        return set()
    role = project_role_for(user, project)
    if role == ProjectRole.PI:
        return set(PI_EDITABLE_FIELDS)
    if role == ProjectRole.MANAGER:
        return set(MANAGER_EDITABLE_FIELDS)
    return set()


def can_manage_members(user, project) -> bool:
    if is_system_admin(user):
        return project.deleted_at is None
    if project.status == ProjectStatus.ARCHIVED or project.deleted_at is not None:
        return False
    return project_role_for(user, project) in {ProjectRole.PI, ProjectRole.MANAGER}


def can_review_access_requests(user, project) -> bool:
    return can_manage_members(user, project)


def can_upload_project_files(user, project) -> bool:
    if not can_view_project(user, project) or project.status == ProjectStatus.ARCHIVED:
        return False
    if is_system_admin(user):
        return True
    return project_role_for(user, project) in {
        ProjectRole.PI,
        ProjectRole.MANAGER,
        ProjectRole.MEMBER,
    }
