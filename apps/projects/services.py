from datetime import datetime
from typing import Any
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditAction
from apps.audit.services import record_audit_event

from .models import (
    AccessRequestStatus,
    MembershipAccessSource,
    Project,
    ProjectAccessRequest,
    ProjectMembership,
    ProjectRole,
    ProjectStatus,
    ProjectType,
    ProjectVisibility,
)
from .permissions import (
    can_manage_members,
    can_review_access_requests,
    can_view_project,
    editable_project_fields,
    is_active_lab_member,
    is_project_portal_user,
    is_system_admin,
)


def _serialize(value: Any):
    if hasattr(value, "pk"):
        return str(value.pk)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _snapshot(instance, fields):
    return {field: _serialize(getattr(instance, field)) for field in fields}


def _ensure_active_lab_member(user):
    if not is_active_lab_member(user):
        raise PermissionDenied("只有正常状态的课题组成员可以执行此操作。")


def _ensure_project_portal_actor(user):
    if not is_project_portal_user(user):
        raise PermissionDenied("只有正常状态的课题组成员或系统管理员可以执行此操作。")


def _lock_user_ids(*user_ids) -> dict[UUID, User]:
    user_ids = {user_id for user_id in user_ids if user_id is not None}
    locked_users = {
        user.pk: user
        for user in User.objects.select_for_update().filter(pk__in=user_ids).order_by("pk")
    }
    if set(locked_users) != user_ids:
        raise ValidationError("用户不存在或已被删除。")
    return locked_users


def _lock_users(*users) -> dict[UUID, User]:
    return _lock_user_ids(*(getattr(user, "pk", None) for user in users))


def _lock_project(project_id, *, include_deleted=False) -> Project:
    projects = Project.all_objects.select_for_update().select_related(
        "project_type",
        "principal_investigator",
    )
    if not include_deleted:
        projects = projects.filter(deleted_at__isnull=True)
    try:
        return projects.get(pk=project_id)
    except Project.DoesNotExist as exc:
        raise ValidationError("项目不存在或已被删除。") from exc


def _lock_projects(project_ids) -> list[Project]:
    normalized_ids = set(project_ids)
    if not normalized_ids:
        return []
    projects = list(
        Project.all_objects.select_for_update().filter(pk__in=normalized_ids).order_by("pk")
    )
    if {project.pk for project in projects} != normalized_ids:
        raise ValidationError("一个或多个项目不存在。")
    return projects


def _lock_project_user_access_state(*, project, user, membership_user_ids=()):
    access_requests = list(
        ProjectAccessRequest.objects.select_for_update()
        .filter(
            project=project,
            requester=user,
        )
        .order_by("pk")
    )
    request_ids = [access_request.pk for access_request in access_requests]
    active_user_ids = {user.pk, *membership_user_ids}
    membership_filter = Q(
        project=project,
        user_id__in=active_user_ids,
        left_at__isnull=True,
    )
    if request_ids:
        membership_filter |= Q(source_access_request_id__in=request_ids)
    memberships = list(
        ProjectMembership.objects.select_for_update().filter(membership_filter).order_by("pk")
    )
    return access_requests, memberships


def _membership_by_request(memberships) -> dict[UUID, ProjectMembership]:
    return {
        membership.source_access_request_id: membership
        for membership in memberships
        if membership.source_access_request_id is not None
    }


def _linked_membership(access_request, memberships) -> ProjectMembership:
    membership = _membership_by_request(memberships).get(access_request.pk)
    if membership is None:
        raise ValidationError("已批准申请缺少对应的授权记录。")
    if (
        membership.project_id != access_request.project_id
        or membership.user_id != access_request.requester_id
    ):
        raise ValidationError("申请授权与来源申请的项目或用户不一致。")
    return membership


def _active_membership(*, project, user, memberships):
    active = [
        membership
        for membership in memberships
        if membership.project_id == project.pk
        and membership.user_id == user.pk
        and membership.left_at is None
    ]
    if len(active) > 1:
        raise ValidationError("同一用户存在多条活动项目成员记录。")
    return active[0] if active else None


def _create_membership(**values) -> ProjectMembership:
    membership = ProjectMembership(**values)
    membership.full_clean()
    try:
        membership.save()
    except IntegrityError as exc:
        raise ValidationError("项目成员授权发生并发冲突，请刷新后重试。") from exc
    return membership


def _close_membership(*, membership, at) -> bool:
    if membership.left_at is not None:
        return False
    membership.left_at = at
    membership.full_clean()
    membership.save(update_fields={"left_at", "updated_at"})
    return True


def _revoke_locked_approved_request(
    *,
    access_request,
    membership,
    actor,
    at,
    description,
    reason,
    http_request=None,
) -> ProjectMembership:
    if access_request.status != AccessRequestStatus.APPROVED:
        raise ValidationError("只能撤销已批准的访问申请。")
    if membership.source_access_request_id != access_request.pk:
        raise ValidationError("成员授权未绑定当前访问申请。")
    _close_membership(membership=membership, at=at)
    access_request.status = AccessRequestStatus.CANCELLED
    access_request.save(update_fields={"status", "updated_at"})
    record_audit_event(
        action=AuditAction.ACCESS_REQUEST_REVOKED,
        request=http_request,
        actor=actor,
        subject=access_request,
        description=description,
        old_value={"status": AccessRequestStatus.APPROVED},
        new_value={
            "status": AccessRequestStatus.CANCELLED,
            "reason": reason,
        },
    )
    return membership


def _cancel_pending_requests_for_direct_assignment(
    *,
    access_requests,
    actor,
    http_request=None,
):
    for access_request in access_requests:
        if access_request.status != AccessRequestStatus.PENDING:
            continue
        access_request.status = AccessRequestStatus.CANCELLED
        access_request.save(update_fields={"status", "updated_at"})
        record_audit_event(
            action=AuditAction.ACCESS_REQUEST_CANCELLED,
            request=http_request,
            actor=actor,
            subject=access_request,
            description="直接项目成员授权替代待处理访问申请",
            old_value={"status": AccessRequestStatus.PENDING},
            new_value={
                "status": AccessRequestStatus.CANCELLED,
                "reason": "superseded_by_direct_assignment",
            },
        )


def _end_request_grant_for_direct_assignment(
    *,
    access_request,
    membership,
    actor,
    at,
    http_request=None,
):
    if membership.access_source != MembershipAccessSource.APPROVED_REQUEST:
        raise ValidationError("只有申请产生的授权可以使用替代流程。")
    if membership.source_access_request_id != access_request.pk:
        raise ValidationError("成员授权未绑定当前访问申请。")
    if access_request.status == AccessRequestStatus.APPROVED:
        _revoke_locked_approved_request(
            access_request=access_request,
            membership=membership,
            actor=actor,
            at=at,
            description="直接项目成员授权替代申请访问授权",
            reason="superseded_by_direct_assignment",
            http_request=http_request,
        )
        return
    elif access_request.status not in {
        AccessRequestStatus.CANCELLED,
        AccessRequestStatus.EXPIRED,
    }:
        raise ValidationError("申请授权与来源申请状态不一致。")

    _close_membership(membership=membership, at=at)


def _expire_locked_requests(*, access_requests, memberships, at) -> int:
    expired_count = 0
    for access_request in access_requests:
        if (
            access_request.status != AccessRequestStatus.APPROVED
            or access_request.expires_at is None
            or access_request.expires_at > at
        ):
            continue
        membership = _linked_membership(access_request, memberships)
        _close_membership(membership=membership, at=at)
        access_request.status = AccessRequestStatus.EXPIRED
        access_request.save(update_fields={"status", "updated_at"})
        record_audit_event(
            action=AuditAction.ACCESS_REQUEST_EXPIRED,
            subject=access_request,
            description="项目访问授权到期",
            old_value={"status": AccessRequestStatus.APPROVED},
            new_value={"status": AccessRequestStatus.EXPIRED},
        )
        expired_count += 1
    return expired_count


@transaction.atomic
def create_project(*, actor, cleaned_data: dict[str, Any], http_request=None) -> Project:
    locked_actor = _lock_users(actor)[actor.pk]
    _ensure_project_portal_actor(locked_actor)
    project_type_id = cleaned_data["project_type"].pk
    try:
        project_type = ProjectType.objects.select_for_update().get(pk=project_type_id)
    except ProjectType.DoesNotExist as exc:
        raise ValidationError("项目类型不存在。") from exc
    if not project_type.is_active:
        raise ValidationError("不能使用已停用的项目类型。")
    if cleaned_data.get("status") == ProjectStatus.ARCHIVED:
        raise ValidationError("新项目不能直接创建为已归档状态。")

    project = Project(
        **{**cleaned_data, "project_type": project_type},
        principal_investigator=locked_actor,
        created_by=locked_actor,
    )
    project.full_clean()
    project.save()
    _create_membership(
        project=project,
        user=locked_actor,
        role=ProjectRole.PI,
        access_source=MembershipAccessSource.DIRECT,
    )
    record_audit_event(
        action=AuditAction.PROJECT_CREATED,
        request=http_request,
        actor=locked_actor,
        subject=project,
        description="创建项目并将创建者设为项目负责人",
        new_value={
            "project_code": project.project_code,
            "name": project.name,
            "status": project.status,
            "visibility": project.visibility,
            "principal_investigator": str(locked_actor.pk),
        },
    )
    return project


def _transfer_pi(
    *,
    project,
    new_pi,
    actor,
    access_requests,
    memberships,
    http_request=None,
):
    if not is_system_admin(actor):
        raise PermissionDenied("只有系统管理员可以更换项目负责人。")
    _ensure_active_lab_member(new_pi)
    if new_pi.pk == project.principal_investigator_id:
        return

    now = timezone.now()
    old_pi_id = project.principal_investigator_id
    _expire_locked_requests(
        access_requests=access_requests,
        memberships=memberships,
        at=now,
    )
    old_membership = next(
        (
            membership
            for membership in memberships
            if membership.project_id == project.pk
            and membership.user_id == old_pi_id
            and membership.role == ProjectRole.PI
            and membership.left_at is None
        ),
        None,
    )
    if old_membership is None:
        raise ValidationError("项目负责人缺少活动 PI 成员关系。")
    new_membership = _active_membership(
        project=project,
        user=new_pi,
        memberships=memberships,
    )

    _cancel_pending_requests_for_direct_assignment(
        access_requests=access_requests,
        actor=actor,
        http_request=http_request,
    )

    project.principal_investigator = new_pi
    project.save(update_fields={"principal_investigator", "updated_at"})

    old_membership.role = ProjectRole.MANAGER
    old_membership.access_source = MembershipAccessSource.DIRECT
    old_membership.source_access_request = None
    old_membership.expires_at = None
    old_membership.full_clean()
    old_membership.save(
        update_fields={
            "role",
            "access_source",
            "source_access_request",
            "expires_at",
            "updated_at",
        }
    )

    if (
        new_membership is not None
        and new_membership.access_source == MembershipAccessSource.APPROVED_REQUEST
    ):
        source_request = next(
            (
                access_request
                for access_request in access_requests
                if access_request.pk == new_membership.source_access_request_id
            ),
            None,
        )
        if source_request is None:
            raise ValidationError("申请授权缺少已锁定的来源申请。")
        _end_request_grant_for_direct_assignment(
            access_request=source_request,
            membership=new_membership,
            actor=actor,
            at=now,
            http_request=http_request,
        )
        new_membership = None

    if new_membership is None:
        _create_membership(
            project=project,
            user=new_pi,
            role=ProjectRole.PI,
            access_source=MembershipAccessSource.DIRECT,
        )
    else:
        new_membership.role = ProjectRole.PI
        new_membership.access_source = MembershipAccessSource.DIRECT
        new_membership.source_access_request = None
        new_membership.expires_at = None
        new_membership.full_clean()
        new_membership.save(
            update_fields={
                "role",
                "access_source",
                "source_access_request",
                "expires_at",
                "updated_at",
            }
        )

    record_audit_event(
        action=AuditAction.PROJECT_PI_TRANSFERRED,
        request=http_request,
        actor=actor,
        subject=project,
        description="系统管理员更换项目负责人",
        old_value={"principal_investigator": str(old_pi_id)},
        new_value={"principal_investigator": str(new_pi.pk)},
    )


@transaction.atomic
def update_project(
    *,
    actor,
    project: Project,
    cleaned_data: dict[str, Any],
    http_request=None,
) -> Project:
    values = dict(cleaned_data)
    new_pi_hint = values.get("principal_investigator")
    user_ids = {actor.pk, project.principal_investigator_id}
    if new_pi_hint is not None:
        user_ids.add(new_pi_hint.pk)
    locked_users = _lock_user_ids(*user_ids)
    locked_actor = locked_users[actor.pk]
    locked = _lock_project(project.pk)
    if (
        new_pi_hint is not None
        and locked.principal_investigator_id != project.principal_investigator_id
    ):
        raise ValidationError("项目负责人已变化，请刷新后重试。")

    requested_type = values.get("project_type")
    if requested_type is not None:
        try:
            locked_type = ProjectType.objects.select_for_update().get(pk=requested_type.pk)
        except ProjectType.DoesNotExist as exc:
            raise ValidationError("项目类型不存在。") from exc
        if not locked_type.is_active and locked_type.pk != locked.project_type_id:
            raise ValidationError("不能将项目切换到已停用的项目类型。")
        values["project_type"] = locked_type

    allowed_fields = editable_project_fields(locked_actor, locked)
    requested_fields = set(values)
    if not requested_fields <= allowed_fields:
        raise PermissionDenied("当前项目角色无权修改一个或多个字段。")
    if values.get("status") == ProjectStatus.ARCHIVED and not is_system_admin(locked_actor):
        raise PermissionDenied("只有系统管理员可以正式归档项目。")

    old_values = _snapshot(locked, requested_fields)
    new_pi = values.pop("principal_investigator", None)
    if new_pi is not None:
        locked_new_pi = locked_users[new_pi.pk]
        access_requests = list(
            ProjectAccessRequest.objects.select_for_update()
            .filter(project=locked, requester=locked_new_pi)
            .order_by("pk")
        )
        request_ids = [access_request.pk for access_request in access_requests]
        membership_filter = Q(
            project=locked,
            user_id__in=(locked.principal_investigator_id, locked_new_pi.pk),
            left_at__isnull=True,
        )
        if request_ids:
            membership_filter |= Q(source_access_request_id__in=request_ids)
        memberships = list(
            ProjectMembership.objects.select_for_update().filter(membership_filter).order_by("pk")
        )
        _transfer_pi(
            project=locked,
            new_pi=locked_new_pi,
            actor=locked_actor,
            access_requests=access_requests,
            memberships=memberships,
            http_request=http_request,
        )

    for field, value in values.items():
        setattr(locked, field, value)
    locked.full_clean()
    locked.save()
    changed_fields = [
        field
        for field in requested_fields
        if old_values[field] != _serialize(getattr(locked, field))
    ]
    if changed_fields:
        action = (
            AuditAction.PROJECT_ARCHIVED
            if locked.status == ProjectStatus.ARCHIVED
            and old_values.get("status") != ProjectStatus.ARCHIVED
            else AuditAction.PROJECT_UPDATED
        )
        record_audit_event(
            action=action,
            request=http_request,
            actor=locked_actor,
            subject=locked,
            description="更新项目基本信息",
            old_value={field: old_values[field] for field in changed_fields},
            new_value={field: _serialize(getattr(locked, field)) for field in changed_fields},
        )
    return locked


@transaction.atomic
def soft_delete_project(*, actor, project: Project, http_request=None) -> Project:
    locked_actor = _lock_users(actor)[actor.pk]
    locked = _lock_project(project.pk)
    if not is_system_admin(locked_actor):
        raise PermissionDenied("只有系统管理员可以软删除项目。")
    locked.deleted_at = timezone.now()
    locked.save(update_fields={"deleted_at", "updated_at"})
    record_audit_event(
        action=AuditAction.PROJECT_SOFT_DELETED,
        request=http_request,
        actor=locked_actor,
        subject=locked,
        description="系统管理员软删除项目",
        new_value={"deleted_at": locked.deleted_at.isoformat()},
    )
    return locked


@transaction.atomic
def set_project_member(
    *,
    actor,
    project: Project,
    user,
    role: str,
    http_request=None,
) -> ProjectMembership:
    if role == ProjectRole.PI or role not in {
        ProjectRole.MANAGER,
        ProjectRole.MEMBER,
        ProjectRole.VIEWER,
    }:
        raise ValidationError("负责人变更必须使用系统管理员专用流程。")

    locked_users = _lock_users(actor, user)
    locked_actor = locked_users[actor.pk]
    locked_user = locked_users[user.pk]
    locked_project = _lock_project(project.pk)
    if not can_manage_members(locked_actor, locked_project):
        raise PermissionDenied("当前用户无权管理项目成员。")
    if locked_project.status == ProjectStatus.ARCHIVED:
        raise ValidationError("已归档项目不能变更普通成员授权。")
    _ensure_active_lab_member(locked_user)

    now = timezone.now()
    access_requests, memberships = _lock_project_user_access_state(
        project=locked_project,
        user=locked_user,
    )
    _expire_locked_requests(
        access_requests=access_requests,
        memberships=memberships,
        at=now,
    )
    _cancel_pending_requests_for_direct_assignment(
        access_requests=access_requests,
        actor=locked_actor,
        http_request=http_request,
    )
    membership = _active_membership(
        project=locked_project,
        user=locked_user,
        memberships=memberships,
    )
    if membership is not None and membership.role == ProjectRole.PI:
        raise ValidationError("不能通过成员管理流程修改项目负责人。")
    if (
        membership is not None
        and membership.access_source == MembershipAccessSource.DIRECT
        and membership.role == role
    ):
        return membership

    old_value = {}
    had_membership = membership is not None
    if membership is not None:
        old_value = {
            "role": membership.role,
            "access_source": membership.access_source,
            "source_access_request": _serialize(membership.source_access_request_id),
            "expires_at": _serialize(membership.expires_at),
        }
    if (
        membership is not None
        and membership.access_source == MembershipAccessSource.APPROVED_REQUEST
    ):
        source_request = next(
            (
                access_request
                for access_request in access_requests
                if access_request.pk == membership.source_access_request_id
            ),
            None,
        )
        if source_request is None:
            raise ValidationError("申请授权缺少已锁定的来源申请。")
        _end_request_grant_for_direct_assignment(
            access_request=source_request,
            membership=membership,
            actor=locked_actor,
            at=now,
            http_request=http_request,
        )
        membership = None

    if membership is None:
        membership = _create_membership(
            project=locked_project,
            user=locked_user,
            role=role,
            access_source=MembershipAccessSource.DIRECT,
        )
        action = (
            AuditAction.PROJECT_MEMBER_UPDATED
            if had_membership
            else AuditAction.PROJECT_MEMBER_ADDED
        )
    else:
        membership.role = role
        membership.access_source = MembershipAccessSource.DIRECT
        membership.source_access_request = None
        membership.expires_at = None
        membership.full_clean()
        membership.save(
            update_fields={
                "role",
                "access_source",
                "source_access_request",
                "expires_at",
                "updated_at",
            }
        )
        action = AuditAction.PROJECT_MEMBER_UPDATED

    record_audit_event(
        action=action,
        request=http_request,
        actor=locked_actor,
        subject=membership,
        description="设置项目成员角色",
        old_value=old_value,
        new_value={
            "role": membership.role,
            "access_source": membership.access_source,
            "user": str(locked_user.pk),
        },
    )
    return membership


@transaction.atomic
def remove_project_member(*, actor, membership: ProjectMembership, http_request=None):
    hint = (
        ProjectMembership.objects.filter(pk=membership.pk)
        .values("project_id", "user_id", "source_access_request_id")
        .first()
    )
    if hint is None:
        raise ValidationError("项目成员记录不存在。")
    locked_users = _lock_user_ids(actor.pk, hint["user_id"])
    locked_actor = locked_users[actor.pk]
    locked_project = _lock_project(hint["project_id"])
    if not can_manage_members(locked_actor, locked_project):
        raise PermissionDenied("当前用户无权管理项目成员。")

    current_hint = (
        ProjectMembership.objects.filter(pk=membership.pk)
        .values("project_id", "user_id", "source_access_request_id")
        .get()
    )
    if (
        current_hint["project_id"] != locked_project.pk
        or current_hint["user_id"] != hint["user_id"]
    ):
        raise ValidationError("项目成员记录已变化，请刷新后重试。")
    access_request = None
    if current_hint["source_access_request_id"] is not None:
        access_request = ProjectAccessRequest.objects.select_for_update().get(
            pk=current_hint["source_access_request_id"]
        )
    locked = ProjectMembership.objects.select_for_update().get(pk=membership.pk)
    if (
        locked.project_id != locked_project.pk
        or locked.user_id != hint["user_id"]
        or locked.source_access_request_id != current_hint["source_access_request_id"]
    ):
        raise ValidationError("项目成员记录已变化，请刷新后重试。")
    if locked.left_at is not None:
        return locked
    if locked.role == ProjectRole.PI:
        raise ValidationError("不能移除项目负责人；请由系统管理员先更换负责人。")
    now = timezone.now()
    if locked.access_source == MembershipAccessSource.APPROVED_REQUEST:
        if access_request is None:
            raise ValidationError("申请授权缺少来源申请。")
        revoked_membership = _revoke_locked_approved_request(
            access_request=access_request,
            membership=locked,
            actor=locked_actor,
            at=now,
            description="项目成员移除操作撤销申请访问授权",
            reason="removed_from_project_members",
            http_request=http_request,
        )
        return revoked_membership

    _close_membership(membership=locked, at=now)
    record_audit_event(
        action=AuditAction.PROJECT_MEMBER_REMOVED,
        request=http_request,
        actor=locked_actor,
        subject=locked,
        description="移除项目成员",
        old_value={"role": locked.role, "user": str(locked.user_id)},
        new_value={"left_at": locked.left_at.isoformat(), "reason": "removed_from_project"},
    )
    return locked


@transaction.atomic
def submit_access_request(
    *,
    actor,
    project: Project,
    reason: str,
    http_request=None,
) -> ProjectAccessRequest:
    locked_actor = _lock_users(actor)[actor.pk]
    locked_project = _lock_project(project.pk)
    _ensure_active_lab_member(locked_actor)
    if locked_project.visibility != ProjectVisibility.RESTRICTED:
        raise ValidationError("只有受限项目需要提交访问申请。")
    if locked_project.status == ProjectStatus.ARCHIVED:
        raise ValidationError("已归档项目不能提交新的访问申请。")
    now = timezone.now()
    access_requests, memberships = _lock_project_user_access_state(
        project=locked_project,
        user=locked_actor,
    )
    _expire_locked_requests(
        access_requests=access_requests,
        memberships=memberships,
        at=now,
    )
    if can_view_project(locked_actor, locked_project, at=now):
        raise ValidationError("当前用户已经拥有项目访问权限。")
    if any(
        access_request.status == AccessRequestStatus.PENDING for access_request in access_requests
    ):
        raise ValidationError("当前项目已有待处理访问申请。")
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValidationError("请填写访问申请用途。")

    access_request = ProjectAccessRequest(
        project=locked_project,
        requester=locked_actor,
        reason=normalized_reason,
    )
    access_request.full_clean()
    try:
        access_request.save()
    except IntegrityError as exc:
        raise ValidationError("访问申请发生并发冲突，请刷新后重试。") from exc
    record_audit_event(
        action=AuditAction.ACCESS_REQUEST_SUBMITTED,
        request=http_request,
        actor=locked_actor,
        subject=access_request,
        description="提交受限项目访问申请",
        new_value={"project": str(locked_project.pk), "status": access_request.status},
    )
    return access_request


@transaction.atomic
def review_access_request(
    *,
    actor,
    access_request: ProjectAccessRequest,
    approve: bool,
    review_note: str = "",
    expires_at: datetime | None = None,
    http_request=None,
) -> ProjectAccessRequest:
    locked_users = _lock_user_ids(actor.pk, access_request.requester_id)
    locked_actor = locked_users[actor.pk]
    locked_requester = locked_users[access_request.requester_id]
    locked_project = _lock_project(access_request.project_id)
    access_requests, memberships = _lock_project_user_access_state(
        project=locked_project,
        user=locked_requester,
        membership_user_ids=(locked_actor.pk,),
    )
    locked = next(
        (candidate for candidate in access_requests if candidate.pk == access_request.pk),
        None,
    )
    if locked is None:
        raise ValidationError("访问申请不存在或关联项目已变化。")
    if locked.status != AccessRequestStatus.PENDING:
        raise ValidationError("只能处理待审核的访问申请。")
    if locked.project_id != locked_project.pk or locked.requester_id != locked_requester.pk:
        raise ValidationError("访问申请关联关系已变化，请刷新后重试。")
    _ensure_active_lab_member(locked_requester)
    if locked_project.visibility != ProjectVisibility.RESTRICTED:
        raise ValidationError("项目已不再是受限项目，不能继续审批。")
    if locked_project.status == ProjectStatus.ARCHIVED:
        raise ValidationError("已归档项目不能审批新的访问授权。")
    if not can_review_access_requests(locked_actor, locked_project):
        raise PermissionDenied("当前用户无权审核该项目的访问申请。")
    if locked_actor.pk == locked.requester_id:
        raise PermissionDenied("不能审核自己的访问申请。")

    now = timezone.now()
    normalized_note = review_note.strip()
    if approve:
        if expires_at is not None and expires_at <= now:
            raise ValidationError("访问到期时间必须晚于当前时间。")
        _expire_locked_requests(
            access_requests=access_requests,
            memberships=memberships,
            at=now,
        )
        membership = _active_membership(
            project=locked_project,
            user=locked_requester,
            memberships=memberships,
        )
        if membership is not None:
            raise ValidationError("申请人已经拥有项目成员授权，请刷新后重试。")
        locked.status = AccessRequestStatus.APPROVED
        locked.expires_at = expires_at
        action = AuditAction.ACCESS_REQUEST_APPROVED
    else:
        if not normalized_note:
            raise ValidationError("拒绝访问申请时必须填写原因。")
        locked.status = AccessRequestStatus.REJECTED
        locked.expires_at = None
        action = AuditAction.ACCESS_REQUEST_REJECTED

    locked.reviewed_by = locked_actor
    locked.review_note = normalized_note
    locked.reviewed_at = now
    locked.full_clean()
    locked.save()
    if approve:
        _create_membership(
            project=locked_project,
            user=locked_requester,
            role=ProjectRole.VIEWER,
            access_source=MembershipAccessSource.APPROVED_REQUEST,
            source_access_request=locked,
            expires_at=expires_at,
        )
    record_audit_event(
        action=action,
        request=http_request,
        actor=locked_actor,
        subject=locked,
        description="处理受限项目访问申请",
        old_value={"status": AccessRequestStatus.PENDING},
        new_value={
            "status": locked.status,
            "expires_at": _serialize(locked.expires_at),
        },
    )
    return locked


@transaction.atomic
def cancel_or_revoke_access_request(
    *,
    actor,
    access_request: ProjectAccessRequest,
    http_request=None,
) -> ProjectAccessRequest:
    locked_users = _lock_user_ids(actor.pk, access_request.requester_id)
    locked_actor = locked_users[actor.pk]
    locked_requester = locked_users[access_request.requester_id]
    locked_project = _lock_project(access_request.project_id)
    try:
        locked = ProjectAccessRequest.objects.select_for_update().get(
            pk=access_request.pk,
            project=locked_project,
            requester=locked_requester,
        )
    except ProjectAccessRequest.DoesNotExist as exc:
        raise ValidationError("访问申请不存在或关联关系已变化。") from exc
    memberships = list(
        ProjectMembership.objects.select_for_update()
        .filter(
            Q(
                project=locked_project,
                user_id__in=(locked_actor.pk, locked_requester.pk),
                left_at__isnull=True,
            )
            | Q(source_access_request=locked)
        )
        .order_by("pk")
    )
    now = timezone.now()
    if locked.status == AccessRequestStatus.PENDING:
        if locked_actor.pk != locked.requester_id:
            raise PermissionDenied("只有申请人可以取消待审核申请。")
        action = AuditAction.ACCESS_REQUEST_CANCELLED
        description = "申请人取消项目访问申请"
    elif locked.status == AccessRequestStatus.APPROVED:
        if not can_review_access_requests(locked_actor, locked_project):
            raise PermissionDenied("当前用户无权撤销项目访问授权。")
        membership = _linked_membership(locked, memberships)
        _revoke_locked_approved_request(
            access_request=locked,
            membership=membership,
            actor=locked_actor,
            at=now,
            description="项目管理者撤销访问授权",
            reason="revoked_by_project_manager",
            http_request=http_request,
        )
        return locked
    else:
        if locked_actor.pk != locked.requester_id and not can_review_access_requests(
            locked_actor,
            locked_project,
        ):
            raise PermissionDenied("当前用户无权操作该访问申请。")
        return locked

    old_status = locked.status
    locked.status = AccessRequestStatus.CANCELLED
    locked.save(update_fields={"status", "updated_at"})
    record_audit_event(
        action=action,
        request=http_request,
        actor=locked_actor,
        subject=locked,
        description=description,
        old_value={"status": old_status},
        new_value={"status": locked.status},
    )
    return locked


@transaction.atomic
def expire_access_grants(*, project=None, user=None, at=None) -> int:
    now = at or timezone.now()
    request_filters = {
        "status": AccessRequestStatus.APPROVED,
        "expires_at__isnull": False,
        "expires_at__lte": now,
    }
    if project is not None:
        request_filters["project"] = project
    if user is not None:
        request_filters["requester"] = user

    candidates = list(
        ProjectAccessRequest.objects.filter(**request_filters)
        .order_by("project_id", "pk")
        .values("pk", "project_id", "requester_id")
    )
    if not candidates:
        return 0

    _lock_user_ids(*(candidate["requester_id"] for candidate in candidates))
    _lock_projects(candidate["project_id"] for candidate in candidates)
    candidate_ids = [candidate["pk"] for candidate in candidates]
    access_requests = list(
        ProjectAccessRequest.objects.select_for_update()
        .filter(pk__in=candidate_ids, **request_filters)
        .order_by("project_id", "pk")
    )
    memberships = list(
        ProjectMembership.objects.select_for_update()
        .filter(source_access_request_id__in=[request.pk for request in access_requests])
        .order_by("project_id", "pk")
    )
    return _expire_locked_requests(
        access_requests=access_requests,
        memberships=memberships,
        at=now,
    )


@transaction.atomic
def terminate_user_project_access(
    *,
    user,
    actor,
    target_status: str,
    at=None,
    http_request=None,
) -> dict[str, int]:
    now = at or timezone.now()
    locked_users = _lock_users(user, actor)
    locked_user = locked_users[user.pk]
    locked_actor = locked_users[actor.pk]
    project_ids = set(
        Project.all_objects.filter(principal_investigator=locked_user).values_list(
            "pk",
            flat=True,
        )
    )
    project_ids.update(
        ProjectAccessRequest.objects.filter(
            requester=locked_user,
            status__in=(AccessRequestStatus.PENDING, AccessRequestStatus.APPROVED),
        ).values_list("project_id", flat=True)
    )
    project_ids.update(
        ProjectMembership.objects.filter(
            user=locked_user,
            left_at__isnull=True,
        ).values_list("project_id", flat=True)
    )
    locked_projects = _lock_projects(project_ids)
    blocking_projects = [
        project.project_code
        for project in locked_projects
        if project.principal_investigator_id == locked_user.pk and project.deleted_at is None
    ]
    if blocking_projects:
        project_codes = "、".join(blocking_projects[:5])
        if len(blocking_projects) > 5:
            project_codes = f"{project_codes} 等 {len(blocking_projects)} 个项目"
        raise ValidationError({"account_status": f"请先转移未软删除项目负责人：{project_codes}。"})

    access_requests = list(
        ProjectAccessRequest.objects.select_for_update()
        .filter(
            requester=locked_user,
            status__in=(AccessRequestStatus.PENDING, AccessRequestStatus.APPROVED),
        )
        .order_by("project_id", "pk")
    )
    request_ids = [access_request.pk for access_request in access_requests]
    membership_filter = Q(user=locked_user, left_at__isnull=True)
    if request_ids:
        membership_filter |= Q(source_access_request_id__in=request_ids)
    memberships = list(
        ProjectMembership.objects.select_for_update()
        .filter(membership_filter)
        .order_by("project_id", "pk")
    )

    expired_count = _expire_locked_requests(
        access_requests=access_requests,
        memberships=memberships,
        at=now,
    )
    pending_count = 0
    revoked_count = 0
    direct_membership_count = 0

    for access_request in access_requests:
        if access_request.status != AccessRequestStatus.PENDING:
            continue
        access_request.status = AccessRequestStatus.CANCELLED
        access_request.save(update_fields={"status", "updated_at"})
        record_audit_event(
            action=AuditAction.ACCESS_REQUEST_CANCELLED,
            request=http_request,
            actor=locked_actor,
            subject=access_request,
            description=f"账号转为 {target_status}，取消待处理项目访问申请",
            old_value={"status": AccessRequestStatus.PENDING},
            new_value={
                "status": AccessRequestStatus.CANCELLED,
                "reason": "account_departure",
            },
        )
        pending_count += 1

    for access_request in access_requests:
        if access_request.status != AccessRequestStatus.APPROVED:
            continue
        membership = _linked_membership(access_request, memberships)
        _revoke_locked_approved_request(
            access_request=access_request,
            membership=membership,
            actor=locked_actor,
            at=now,
            description=f"账号转为 {target_status}，撤销项目访问授权",
            reason="account_departure",
            http_request=http_request,
        )
        revoked_count += 1

    for membership in memberships:
        if membership.user_id != locked_user.pk or membership.left_at is not None:
            continue
        if membership.access_source == MembershipAccessSource.APPROVED_REQUEST:
            raise ValidationError("活动申请授权与来源申请状态不一致。")
        _close_membership(membership=membership, at=now)
        record_audit_event(
            action=AuditAction.PROJECT_MEMBER_REMOVED,
            request=http_request,
            actor=locked_actor,
            subject=membership,
            description=f"账号转为 {target_status}，结束直接项目成员关系",
            old_value={
                "role": membership.role,
                "user": str(locked_user.pk),
            },
            new_value={
                "left_at": membership.left_at.isoformat(),
                "reason": "account_departure",
            },
        )
        direct_membership_count += 1

    return {
        "expired_requests": expired_count,
        "cancelled_pending_requests": pending_count,
        "revoked_approved_requests": revoked_count,
        "ended_direct_memberships": direct_membership_count,
    }
