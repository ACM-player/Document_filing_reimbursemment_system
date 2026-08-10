import ipaddress
from typing import Any

from django.http import HttpRequest

from .models import AuditAction, AuditLog, AuditResult


def client_ip_from_request(request: HttpRequest | None) -> str | None:
    if request is None:
        return None
    candidate = request.META.get("REMOTE_ADDR", "")
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def record_audit_event(
    *,
    action: AuditAction | str,
    request: HttpRequest | None = None,
    actor=None,
    subject=None,
    description: str = "",
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    result: AuditResult | str = AuditResult.SUCCESS,
) -> AuditLog:
    object_type = ""
    object_id = ""
    if subject is not None:
        object_type = subject._meta.label
        object_id = str(subject.pk)

    request_id = getattr(request, "request_id", None) if request is not None else None
    user_agent = request.META.get("HTTP_USER_AGENT", "")[:512] if request else ""

    return AuditLog.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        actor_username=actor.get_username() if getattr(actor, "is_authenticated", False) else "",
        action=action,
        object_type=object_type,
        object_id=object_id,
        description=description,
        old_value=old_value or {},
        new_value=new_value or {},
        ip_address=client_ip_from_request(request),
        user_agent=user_agent,
        request_id=request_id,
        result=result,
    )
