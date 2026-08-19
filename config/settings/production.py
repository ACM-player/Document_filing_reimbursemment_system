from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import SECRET_KEY

DEBUG = False
LABARCHIVE_REQUIRE_MALWARE_SCAN = True

if SECRET_KEY.startswith("development-only-"):
    raise ImproperlyConfigured("LABARCHIVE_SECRET_KEY must be set in production.")

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False
