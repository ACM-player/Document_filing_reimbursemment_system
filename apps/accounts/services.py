import secrets

from django.db import transaction

from apps.audit.models import AuditAction
from apps.audit.services import record_audit_event

from .constants import SYSTEM_ADMIN_GROUP
from .models import User


def sync_staff_flag(user: User) -> None:
    should_be_staff = user.is_superuser or user.groups.filter(name=SYSTEM_ADMIN_GROUP).exists()
    if user.is_staff != should_be_staff:
        user.is_staff = should_be_staff
        user.save(update_fields={"is_staff", "updated_at"})


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
