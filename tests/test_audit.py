import uuid

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from apps.audit.models import AuditAction, AuditLog
from apps.audit.services import record_audit_event

pytestmark = pytest.mark.django_db


def test_audit_records_are_append_only_through_model_and_queryset_apis():
    event = AuditLog.objects.create(action=AuditAction.LOGIN_FAILED)

    event.description = "changed"
    with pytest.raises(TypeError, match="append-only"):
        event.save()
    with pytest.raises(TypeError, match="append-only"):
        event.delete()
    with pytest.raises(TypeError, match="append-only"):
        AuditLog.objects.filter(pk=event.pk).update(description="changed")
    with pytest.raises(TypeError, match="append-only"):
        AuditLog.objects.filter(pk=event.pk).delete()


def test_audit_service_snapshots_identity_and_request_metadata():
    user = get_user_model().objects.create_user(username="audit-member")
    request = RequestFactory().get(
        "/",
        REMOTE_ADDR="2001:db8::7",
        HTTP_USER_AGENT="x" * 600,
    )
    request.request_id = uuid.uuid4()

    event = record_audit_event(
        action=AuditAction.PROFILE_UPDATED,
        request=request,
        actor=user,
        subject=user,
        new_value={"changed_fields": ["display_name"]},
    )

    assert event.actor == user
    assert event.actor_username == "audit-member"
    assert event.object_type == "accounts.User"
    assert event.object_id == str(user.pk)
    assert event.ip_address == "2001:db8::7"
    assert event.request_id == request.request_id
    assert len(event.user_agent) == 512
