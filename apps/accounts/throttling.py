import hashlib
import hmac
import ipaddress
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import LoginThrottle


def normalized_source_ip(value: str | None) -> str:
    try:
        return str(ipaddress.ip_address(value or ""))
    except ValueError:
        return "0.0.0.0"


def username_fingerprint(username: str) -> str:
    normalized = username.strip().casefold().encode()
    secret = settings.SECRET_KEY.encode()
    return hmac.new(secret, normalized, hashlib.sha256).hexdigest()


def _key(username: str, source_ip: str | None) -> dict[str, str]:
    return {
        "username_fingerprint": username_fingerprint(username),
        "source_ip": normalized_source_ip(source_ip),
    }


@transaction.atomic
def is_login_locked(username: str, source_ip: str | None) -> bool:
    throttle = LoginThrottle.objects.select_for_update().filter(**_key(username, source_ip)).first()
    if throttle is None or throttle.locked_until is None:
        return False
    now = timezone.now()
    if throttle.locked_until > now:
        return True
    throttle.delete()
    return False


@transaction.atomic
def register_login_failure(username: str, source_ip: str | None) -> bool:
    now = timezone.now()
    window = timedelta(seconds=settings.LOGIN_FAILURE_WINDOW_SECONDS)
    lock_duration = timedelta(seconds=settings.LOGIN_LOCKOUT_SECONDS)
    throttle, _ = LoginThrottle.objects.select_for_update().get_or_create(
        **_key(username, source_ip),
        defaults={"window_started_at": now},
    )

    if now - throttle.window_started_at >= window:
        throttle.failure_count = 0
        throttle.window_started_at = now
        throttle.locked_until = None

    throttle.failure_count += 1
    if throttle.failure_count >= settings.LOGIN_MAX_FAILURES:
        throttle.locked_until = now + lock_duration
    throttle.save()
    return throttle.locked_until is not None and throttle.locked_until > now


def clear_login_failures(username: str, source_ip: str | None) -> None:
    LoginThrottle.objects.filter(**_key(username, source_ip)).delete()
