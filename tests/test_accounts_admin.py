from unittest.mock import Mock, patch

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client
from django.test.client import RequestFactory
from django.urls import reverse

from apps.accounts.admin import LabArchiveUserAdmin
from apps.accounts.constants import LAB_MEMBER_GROUP, SYSTEM_ADMIN_GROUP
from apps.accounts.forms import LabArchiveUserChangeForm, LabArchiveUserCreationForm
from apps.accounts.models import AccountStatus
from apps.audit.models import AuditAction, AuditLog
from apps.projects.models import ProjectMembership, ProjectRole, ProjectVisibility

from .project_factories import make_project

pytestmark = pytest.mark.django_db


def _admin_user_change_payload(user, *, account_status):
    profile = user.profile
    return {
        "username": user.username,
        "display_name": user.display_name,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "account_status": account_status,
        "groups": [str(group_id) for group_id in user.groups.values_list("pk", flat=True)],
        "profile-TOTAL_FORMS": "1",
        "profile-INITIAL_FORMS": "1",
        "profile-MIN_NUM_FORMS": "0",
        "profile-MAX_NUM_FORMS": "1",
        "profile-0-id": str(profile.pk),
        "profile-0-department": profile.department,
        "profile-0-student_or_staff_id": profile.student_or_staff_id,
        "profile-0-phone": profile.phone,
        "profile-0-notes": profile.notes,
        "_save": "保存",
    }


def test_superuser_can_generate_one_time_temporary_password():
    admin_user = get_user_model().objects.create_superuser(
        username="emergency-admin",
        password="Admin-strong-password-2026!",
    )
    target = get_user_model().objects.create_user(
        username="password-reset-target",
        password="Original-strong-password-2026!",
    )
    client = Client()
    client.force_login(admin_user)
    url = reverse("admin:accounts_user_reset_temporary_password", args=(target.pk,))

    get_response = client.get(url)
    assert get_response.status_code == 200
    assert "temporary-password-from-test" not in get_response.content.decode()
    assert "no-store" in get_response.headers["Cache-Control"]

    with patch(
        "apps.accounts.services.secrets.token_urlsafe",
        return_value="temporary-password-from-test",
    ):
        post_response = client.post(url)

    assert post_response.status_code == 200
    assert "temporary-password-from-test" in post_response.content.decode()
    assert "no-store" in post_response.headers["Cache-Control"]
    target.refresh_from_db()
    assert target.must_change_password is True
    assert target.check_password("temporary-password-from-test")
    event = AuditLog.objects.get(action=AuditAction.PASSWORD_RESET_BY_ADMIN)
    assert event.actor == admin_user
    assert event.object_id == str(target.pk)
    assert event.new_value == {"must_change_password": True}


def test_admin_creation_form_sets_first_login_password_change():
    form = LabArchiveUserCreationForm(
        data={
            "username": "admin-created-member",
            "display_name": "Admin Created",
            "email": "created@example.com",
            "account_status": AccountStatus.ACTIVE,
            "password1": "Temporary-strong-password-2026!",
            "password2": "Temporary-strong-password-2026!",
        }
    )

    assert form.is_valid(), form.errors
    user = form.save()

    assert user.must_change_password is True
    assert set(user.groups.values_list("name", flat=True)) == {LAB_MEMBER_GROUP}


def test_admin_status_change_is_synchronized_and_audited():
    admin_user = get_user_model().objects.create_superuser(username="status-admin")
    target = get_user_model().objects.create_user(username="status-target")
    request = RequestFactory().post("/admin/accounts/user/")
    request.user = admin_user
    model_admin = LabArchiveUserAdmin(get_user_model(), admin.site)

    target.account_status = AccountStatus.DEPARTED
    model_admin.save_model(request, target, form=None, change=True)

    target.refresh_from_db()
    assert target.is_active is False
    event = AuditLog.objects.get(action=AuditAction.USER_STATUS_CHANGED)
    assert event.actor == admin_user
    assert event.old_value == {"account_status": AccountStatus.ACTIVE}
    assert event.new_value == {"account_status": AccountStatus.DEPARTED}


def test_admin_change_post_departure_closes_restricted_direct_membership():
    admin_user = get_user_model().objects.create_superuser(
        username="departure-post-admin",
        password="Admin-strong-password-2026!",
    )
    pi = get_user_model().objects.create_user(username="departure-post-pi")
    target = get_user_model().objects.create_user(username="departure-post-target")
    project = make_project(
        pi=pi,
        code="ADMIN-DEPARTURE",
        visibility=ProjectVisibility.RESTRICTED,
    )
    membership = ProjectMembership.objects.create(
        project=project,
        user=target,
        role=ProjectRole.MEMBER,
    )
    client = Client()
    client.force_login(admin_user)

    response = client.post(
        reverse("admin:accounts_user_change", args=(target.pk,)),
        _admin_user_change_payload(target, account_status=AccountStatus.DEPARTED),
    )

    assert response.status_code == 302
    target.refresh_from_db()
    membership.refresh_from_db()
    assert target.account_status == AccountStatus.DEPARTED
    assert target.is_active is False
    assert membership.left_at is not None
    assert AuditLog.objects.filter(
        action=AuditAction.PROJECT_MEMBER_REMOVED,
        object_id=str(membership.pk),
        actor=admin_user,
    ).exists()
    assert AuditLog.objects.filter(
        action=AuditAction.USER_STATUS_CHANGED,
        object_id=str(target.pk),
        actor=admin_user,
    ).exists()


def test_admin_change_post_pi_departure_returns_form_error_and_preserves_relationship():
    admin_user = get_user_model().objects.create_superuser(
        username="pi-departure-post-admin",
        password="Admin-strong-password-2026!",
    )
    pi = get_user_model().objects.create_user(username="pi-departure-post-target")
    project = make_project(
        pi=pi,
        code="ADMIN-PI-BLOCK",
        visibility=ProjectVisibility.RESTRICTED,
    )
    pi_membership = ProjectMembership.objects.get(
        project=project,
        user=pi,
        role=ProjectRole.PI,
        left_at__isnull=True,
    )
    client = Client()
    client.force_login(admin_user)

    response = client.post(
        reverse("admin:accounts_user_change", args=(pi.pk,)),
        _admin_user_change_payload(pi, account_status=AccountStatus.DEPARTED),
    )

    assert response.status_code == 200
    assert "请先转移未软删除项目负责人" in response.content.decode()
    assert project.project_code in response.content.decode()
    pi.refresh_from_db()
    project.refresh_from_db()
    pi_membership.refresh_from_db()
    assert pi.account_status == AccountStatus.ACTIVE
    assert pi.is_active is True
    assert project.principal_investigator == pi
    assert pi_membership.left_at is None
    assert not AuditLog.objects.filter(
        action=AuditAction.USER_STATUS_CHANGED,
        object_id=str(pi.pk),
    ).exists()


def test_admin_role_assignment_sets_staff_and_creates_role_audit():
    admin_user = get_user_model().objects.create_superuser(username="role-admin")
    target = get_user_model().objects.create_user(username="role-target")
    system_group = Group.objects.get(name=SYSTEM_ADMIN_GROUP)
    request = RequestFactory().post("/admin/accounts/user/")
    request.user = admin_user
    model_admin = LabArchiveUserAdmin(get_user_model(), admin.site)

    model_admin.save_model(request, target, form=None, change=True)
    form = Mock(instance=target)
    form.save_m2m.side_effect = lambda: target.groups.add(system_group)
    model_admin.save_related(request, form, formsets=[], change=True)

    target.refresh_from_db()
    assert target.is_staff is True
    event = AuditLog.objects.get(action=AuditAction.ROLE_ASSIGNED)
    assert event.actor == admin_user
    assert event.new_value == {"role": SYSTEM_ADMIN_GROUP}


def test_admin_change_form_only_offers_predefined_groups():
    target = get_user_model().objects.create_user(username="role-form-target")
    Group.objects.create(name="UNMANAGED_ROLE")

    form = LabArchiveUserChangeForm(instance=target)

    assert set(form.fields["groups"].queryset.values_list("name", flat=True)) == {
        LAB_MEMBER_GROUP,
        "REIMBURSEMENT_ADMIN",
        SYSTEM_ADMIN_GROUP,
    }
