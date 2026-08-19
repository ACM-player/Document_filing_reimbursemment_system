import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction

from apps.accounts.constants import (
    LAB_MEMBER_GROUP,
    REIMBURSEMENT_ADMIN_GROUP,
    SYSTEM_ADMIN_GROUP,
)
from apps.accounts.models import AccountStatus, UserProfile
from apps.accounts.services import sync_staff_flag

pytestmark = pytest.mark.django_db


def test_system_roles_are_seeded_with_expected_permissions():
    member = Group.objects.get(name=LAB_MEMBER_GROUP)
    reimbursement = Group.objects.get(name=REIMBURSEMENT_ADMIN_GROUP)
    system_admin = Group.objects.get(name=SYSTEM_ADMIN_GROUP)

    assert member.permissions.count() == 0
    assert reimbursement.permissions.count() == 0
    system_permissions = set(system_admin.permissions.values_list("codename", flat=True))
    assert {
        "add_user",
        "assign_system_roles",
        "change_user",
        "change_user_status",
        "change_userprofile",
        "reset_user_password",
        "view_auditlog",
        "view_user",
        "view_userprofile",
    } <= system_permissions
    assert {
        "add_project",
        "change_project",
        "delete_project",
        "view_project",
        "archive_project",
        "transfer_project_pi",
        "soft_delete_project",
        "add_projecttype",
        "change_projecttype",
        "delete_projecttype",
        "view_projecttype",
        "add_projectmembership",
        "change_projectmembership",
        "delete_projectmembership",
        "view_projectmembership",
        "add_projectaccessrequest",
        "change_projectaccessrequest",
        "delete_projectaccessrequest",
        "view_projectaccessrequest",
    } <= system_permissions


def test_new_user_gets_profile_and_baseline_member_role():
    user = get_user_model().objects.create_user(username="new-member")

    assert UserProfile.objects.filter(user=user).exists()
    assert set(user.groups.values_list("name", flat=True)) == {LAB_MEMBER_GROUP}


def test_account_status_controls_authentication_flag_and_database_constraint():
    user = get_user_model().objects.create_user(username="lifecycle-user")

    user.account_status = AccountStatus.DISABLED
    user.save(update_fields={"account_status", "updated_at"})
    user.refresh_from_db()

    assert user.is_active is False

    with pytest.raises(IntegrityError), transaction.atomic():
        get_user_model().objects.filter(pk=user.pk).update(is_active=True)

    user.refresh_from_db()
    assert user.account_status == AccountStatus.DISABLED
    assert user.is_active is False


def test_system_admin_role_can_be_synchronized_to_staff_access():
    user = get_user_model().objects.create_user(username="system-admin")
    system_admin = Group.objects.get(name=SYSTEM_ADMIN_GROUP)

    user.groups.add(system_admin)
    sync_staff_flag(user)
    user.refresh_from_db()
    assert user.is_staff is True

    user.groups.remove(system_admin)
    sync_staff_flag(user)
    user.refresh_from_db()
    assert user.is_staff is False
