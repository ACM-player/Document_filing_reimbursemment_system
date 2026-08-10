import json

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.accounts.forms import GENERIC_LOGIN_ERROR
from apps.accounts.models import AccountStatus, LoginThrottle
from apps.audit.models import AuditAction, AuditLog, AuditResult

pytestmark = pytest.mark.django_db

OLD_PASSWORD = "Initial-strong-password-2026!"
NEW_PASSWORD = "Updated-strong-password-2026!"


def _create_user(username="member", **kwargs):
    return get_user_model().objects.create_user(
        username=username,
        password=OLD_PASSWORD,
        **kwargs,
    )


def test_successful_login_is_audited_and_preserves_safe_next_url():
    user = _create_user()
    response = Client().post(
        reverse("accounts:login"),
        {"username": user.username, "password": OLD_PASSWORD, "next": "/accounts/profile/"},
        REMOTE_ADDR="127.0.0.7",
        HTTP_USER_AGENT="Phase1 test agent",
    )

    assert response.status_code == 302
    assert response.url == reverse("accounts:profile")
    event = AuditLog.objects.get(action=AuditAction.LOGIN_SUCCESS)
    assert event.actor == user
    assert event.actor_username == user.username
    assert event.ip_address == "127.0.0.7"
    assert event.user_agent == "Phase1 test agent"
    assert str(event.request_id) == response.headers["X-Request-ID"]


def test_login_rejects_external_next_url():
    user = _create_user()

    response = Client().post(
        reverse("accounts:login"),
        {
            "username": user.username,
            "password": OLD_PASSWORD,
            "next": "https://attacker.example/steal",
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("home")


def test_first_login_forces_password_change_and_invalidates_other_sessions():
    user = _create_user(must_change_password=True)
    first_client = Client()
    second_client = Client()
    second_client.force_login(user)

    response = first_client.post(
        reverse("accounts:login"),
        {"username": user.username, "password": OLD_PASSWORD},
    )
    assert response.status_code == 302
    assert response.url == reverse("accounts:password_change")
    assert first_client.get(reverse("home")).url == reverse("accounts:password_change")

    response = first_client.post(
        reverse("accounts:password_change"),
        {
            "old_password": OLD_PASSWORD,
            "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("home")
    user.refresh_from_db()
    assert user.must_change_password is False
    assert user.check_password(NEW_PASSWORD)
    assert first_client.get(reverse("home")).status_code == 200
    assert second_client.get(reverse("home")).status_code == 302
    assert AuditLog.objects.filter(
        action=AuditAction.PASSWORD_CHANGED,
        actor=user,
    ).exists()


def test_five_failed_logins_lock_username_and_ip_without_storing_credentials():
    user = _create_user(username="locked-member")
    client = Client()
    login_url = reverse("accounts:login")

    for _ in range(settings.LOGIN_MAX_FAILURES):
        response = client.post(
            login_url,
            {"username": user.username, "password": "wrong-secret-value"},
            REMOTE_ADDR="192.0.2.10",
        )
        assert response.status_code == 200
        assert GENERIC_LOGIN_ERROR in response.content.decode()

    throttle = LoginThrottle.objects.get(source_ip="192.0.2.10")
    assert throttle.failure_count == settings.LOGIN_MAX_FAILURES
    assert throttle.locked_until is not None

    response = client.post(
        login_url,
        {"username": user.username, "password": OLD_PASSWORD},
        REMOTE_ADDR="192.0.2.10",
    )
    assert response.status_code == 200
    assert GENERIC_LOGIN_ERROR in response.content.decode()

    events = AuditLog.objects.filter(action=AuditAction.LOGIN_FAILED)
    assert events.count() == settings.LOGIN_MAX_FAILURES + 1
    assert events.filter(result=AuditResult.DENIED).count() == events.count()
    serialized_events = json.dumps(
        list(events.values("old_value", "new_value", "description")),
        ensure_ascii=False,
    )
    assert user.username not in serialized_events
    assert "wrong-secret-value" not in serialized_events
    assert OLD_PASSWORD not in serialized_events


@pytest.mark.parametrize(
    "account_status",
    [AccountStatus.DISABLED, AccountStatus.DEPARTED, AccountStatus.ARCHIVED],
)
def test_non_active_account_gets_same_generic_login_error(account_status):
    user = _create_user(username=f"{account_status.lower()}-member")
    user.account_status = account_status
    user.save(update_fields={"account_status", "updated_at"})

    response = Client().post(
        reverse("accounts:login"),
        {"username": user.username, "password": OLD_PASSWORD},
    )

    assert response.status_code == 200
    assert GENERIC_LOGIN_ERROR in response.content.decode()


def test_disabling_account_invalidates_existing_session_on_next_request():
    user = _create_user(username="session-disabled-member")
    client = Client()
    client.force_login(user)

    assert client.get(reverse("home")).status_code == 200
    user.account_status = AccountStatus.DISABLED
    user.save(update_fields={"account_status", "updated_at"})

    response = client.get(reverse("home"))
    assert response.status_code == 302
    assert response.url == f"{reverse('accounts:login')}?next=/"


def test_profile_only_updates_self_service_fields_and_audits_field_names():
    user = _create_user(username="profile-member")
    client = Client()
    client.force_login(user)

    response = client.post(
        reverse("accounts:profile"),
        {
            "user-display_name": "New Display Name",
            "user-email": "new@example.com",
            "user-username": "attempted-rename",
            "user-account_status": AccountStatus.ARCHIVED,
            "profile-department": "能源与动力工程学院",
            "profile-student_or_staff_id": "STAFF-001",
            "profile-phone": "123456789",
            "profile-notes": "attempted admin-note edit",
        },
    )

    assert response.status_code == 302
    user.refresh_from_db()
    user.profile.refresh_from_db()
    assert user.username == "profile-member"
    assert user.account_status == AccountStatus.ACTIVE
    assert user.display_name == "New Display Name"
    assert user.email == "new@example.com"
    assert user.profile.department == "能源与动力工程学院"
    assert user.profile.notes == ""
    event = AuditLog.objects.get(action=AuditAction.PROFILE_UPDATED)
    assert event.new_value == {
        "changed_fields": [
            "department",
            "display_name",
            "email",
            "phone",
            "student_or_staff_id",
        ]
    }


def test_logout_is_post_only_and_audited():
    user = _create_user(username="logout-member")
    client = Client()
    client.force_login(user)

    assert client.get(reverse("accounts:logout")).status_code == 405
    response = client.post(reverse("accounts:logout"))

    assert response.status_code == 302
    assert response.url == reverse("accounts:login")
    assert AuditLog.objects.filter(action=AuditAction.LOGOUT, actor=user).exists()


def test_session_security_policy_is_explicit():
    assert settings.SESSION_COOKIE_AGE == 12 * 60 * 60
    assert settings.SESSION_EXPIRE_AT_BROWSER_CLOSE is True
    assert settings.SESSION_COOKIE_HTTPONLY is True
