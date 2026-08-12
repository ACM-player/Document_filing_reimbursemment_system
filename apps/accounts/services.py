import secrets

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.audit.models import AuditAction
from apps.audit.services import record_audit_event

from .constants import SYSTEM_ADMIN_GROUP
from .models import AccountStatus, User

ALLOWED_ACCOUNT_STATUS_TRANSITIONS = {
    AccountStatus.ACTIVE: frozenset({AccountStatus.DISABLED, AccountStatus.DEPARTED}),
    AccountStatus.DISABLED: frozenset({AccountStatus.ACTIVE, AccountStatus.DEPARTED}),
    AccountStatus.DEPARTED: frozenset({AccountStatus.ARCHIVED}),
    AccountStatus.ARCHIVED: frozenset(),
}
PERMANENT_ACCOUNT_STATUSES = frozenset({AccountStatus.DEPARTED, AccountStatus.ARCHIVED})


def validate_user_status_transition(*, old_status: str, new_status: str) -> None:
    if new_status not in AccountStatus.values:
        raise ValidationError({"account_status": "未知账号状态。"})
    if old_status == new_status:
        return
    if new_status not in ALLOWED_ACCOUNT_STATUS_TRANSITIONS.get(old_status, frozenset()):
        raise ValidationError(
            {"account_status": f"不允许从 {old_status} 直接变更为 {new_status}。"}
        )


def sync_staff_flag(user: User) -> None:
    should_be_staff = user.is_superuser or user.groups.filter(name=SYSTEM_ADMIN_GROUP).exists()
    if user.is_staff != should_be_staff:
        user.is_staff = should_be_staff
        user.save(update_fields={"is_staff", "updated_at"})


@transaction.atomic
def change_user_status(
    *,
    user: User,
    new_status: str,
    actor: User,
    request=None,
) -> User:
    if not getattr(actor, "is_authenticated", False):
        raise PermissionDenied("当前用户无权修改账号生命周期。")

    user_ids = {actor.pk, user.pk}
    locked_users = {
        candidate.pk: candidate
        for candidate in User.objects.select_for_update().filter(pk__in=user_ids).order_by("pk")
    }
    if set(locked_users) != user_ids:
        raise ValidationError({"account_status": "用户不存在或已被删除。"})
    locked_actor = locked_users[actor.pk]
    locked_user = locked_users[user.pk]
    if not locked_actor.has_perm("accounts.change_user_status"):
        raise PermissionDenied("当前用户无权修改账号生命周期。")
    old_status = locked_user.account_status
    validate_user_status_transition(old_status=old_status, new_status=new_status)
    if old_status == new_status:
        return locked_user
    if locked_user.is_superuser and new_status != AccountStatus.ACTIVE:
        raise ValidationError({"account_status": "不能禁用应急超级管理员。"})

    if new_status in PERMANENT_ACCOUNT_STATUSES:
        from apps.projects.services import terminate_user_project_access

        terminate_user_project_access(
            user=locked_user,
            actor=locked_actor,
            target_status=new_status,
            http_request=request,
        )
    elif new_status == AccountStatus.ACTIVE:
        from apps.projects.services import expire_access_grants

        expire_access_grants(user=locked_user)

    locked_user.account_status = new_status
    locked_user.save(update_fields={"account_status", "updated_at"})
    record_audit_event(
        action=AuditAction.USER_STATUS_CHANGED,
        request=request,
        actor=locked_actor,
        subject=locked_user,
        description="系统管理员修改账号状态",
        old_value={"account_status": old_status},
        new_value={"account_status": new_status},
    )
    return locked_user


@transaction.atomic
def reset_temporary_password(*, user: User, actor: User, request=None) -> str:
    locked_user = User.objects.select_for_update().get(pk=user.pk)
    temporary_password = secrets.token_urlsafe(16)
    locked_user.set_password(temporary_password)
    locked_user.must_change_password = True
    locked_user.save(update_fields={"password", "must_change_password", "updated_at"})
    record_audit_event(
        action=AuditAction.PASSWORD_RESET_BY_ADMIN,
        request=request,
        actor=actor,
        subject=locked_user,
        description="管理员生成一次性临时密码",
        new_value={"must_change_password": True},
    )
    return temporary_password
