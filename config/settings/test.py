from .base import *  # noqa: F403
from .base import BASE_DIR

DEBUG = False
MEDIA_ROOT = BASE_DIR / ".local" / "test-media"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
