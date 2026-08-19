from django.contrib.auth.models import Group, Permission
from django.db.models.signals import post_migrate, post_save
from django.dispatch import receiver

from .constants import (
    LAB_MEMBER_GROUP,
    REIMBURSEMENT_ADMIN_GROUP,
    SYSTEM_ADMIN_GROUP,
)
from .models import User, UserProfile


@receiver(post_save, sender=User, dispatch_uid="accounts_create_profile_and_member_role")
def create_profile_and_member_role(sender, instance, created, **kwargs):
    if not created:
        return
    UserProfile.objects.get_or_create(user=instance)
    member_group = Group.objects.filter(name=LAB_MEMBER_GROUP).first()
    if member_group is not None:
        instance.groups.add(member_group)


@receiver(post_migrate, dispatch_uid="accounts_seed_system_groups")
def seed_system_groups(sender, **kwargs):
    if sender.label not in {"accounts", "audit", "projects"}:
        return

    member_group, _ = Group.objects.get_or_create(name=LAB_MEMBER_GROUP)
    reimbursement_group, _ = Group.objects.get_or_create(name=REIMBURSEMENT_ADMIN_GROUP)
    system_group, _ = Group.objects.get_or_create(name=SYSTEM_ADMIN_GROUP)

    member_group.permissions.clear()
    reimbursement_group.permissions.clear()

    desired_permissions = (
        Permission.objects.filter(
            content_type__app_label="accounts",
            codename__in=(
                "add_user",
                "change_user",
                "view_user",
                "view_userprofile",
                "change_userprofile",
                "reset_user_password",
                "change_user_status",
                "assign_system_roles",
            ),
        )
        | Permission.objects.filter(
            content_type__app_label="audit",
            codename="view_auditlog",
        )
        | Permission.objects.filter(
            content_type__app_label="projects",
        )
    )
    system_group.permissions.set(desired_permissions)

    # Migrations can create users before the role rows exist (for example when
    # restoring a local database). Keep the baseline role/profile invariant
    # true for those existing accounts as well as newly created accounts.
    member_group.user_set.add(*User.objects.all())
    for user in User.objects.iterator():
        UserProfile.objects.get_or_create(user=user)
