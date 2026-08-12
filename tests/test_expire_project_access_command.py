from datetime import timedelta
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.audit.models import AuditAction, AuditLog
from apps.projects.models import AccessRequestStatus, ProjectVisibility
from apps.projects.services import review_access_request, submit_access_request

from .project_factories import make_project, make_user


def test_command_delegates_to_expiration_service_once():
    output = StringIO()

    with patch(
        "apps.projects.management.commands.expire_project_access.expire_access_grants",
        return_value=3,
    ) as expire_grants:
        call_command(
            "expire_project_access",
            batch_size=25,
            stdout=output,
            no_color=True,
        )

    expire_grants.assert_called_once_with()
    assert "Expired 3 project access grant(s)." in output.getvalue()
    assert "processed all eligible grants in one transaction" in output.getvalue()


@pytest.mark.django_db
def test_command_expires_grants_and_is_idempotent():
    owner = make_user("expiry-command-owner")
    requester = make_user("expiry-command-requester")
    project = make_project(
        pi=owner,
        code="EXPIRY-COMMAND",
        visibility=ProjectVisibility.RESTRICTED,
    )
    expires_at = timezone.now() + timedelta(days=1)
    access_request = submit_access_request(
        actor=requester,
        project=project,
        reason="验证定时到期归一化",
    )
    access_request = review_access_request(
        actor=owner,
        access_request=access_request,
        approve=True,
        expires_at=expires_at,
    )
    membership = access_request.granted_membership
    command_time = expires_at + timedelta(seconds=1)
    first_output = StringIO()

    with patch("apps.projects.services.timezone.now", return_value=command_time):
        call_command(
            "expire_project_access",
            batch_size=25,
            stdout=first_output,
            no_color=True,
        )

    access_request.refresh_from_db()
    membership.refresh_from_db()
    assert access_request.status == AccessRequestStatus.EXPIRED
    assert membership.left_at == command_time
    assert AuditLog.objects.filter(action=AuditAction.ACCESS_REQUEST_EXPIRED).count() == 1
    assert "Expired 1 project access grant(s)." in first_output.getvalue()
    assert "processed all eligible grants in one transaction" in first_output.getvalue()

    second_output = StringIO()
    with patch("apps.projects.services.timezone.now", return_value=command_time):
        call_command("expire_project_access", stdout=second_output, no_color=True)

    membership.refresh_from_db()
    assert membership.left_at == command_time
    assert AuditLog.objects.filter(action=AuditAction.ACCESS_REQUEST_EXPIRED).count() == 1
    assert "Expired 0 project access grant(s)." in second_output.getvalue()


@pytest.mark.parametrize("batch_size", [0, -1, "not-an-integer", True])
def test_command_rejects_invalid_batch_size(batch_size):
    with pytest.raises(CommandError, match="--batch-size must be a positive integer"):
        call_command("expire_project_access", batch_size=batch_size, no_color=True)
