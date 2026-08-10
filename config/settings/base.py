from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parents[2]

env = environ.Env(
    LABARCHIVE_DEBUG=(bool, False),
    POSTGRES_PORT=(int, 5432),
    POSTGRES_CONN_MAX_AGE=(int, 0),
    LABARCHIVE_MAX_UPLOAD_SIZE=(int, 100 * 1024 * 1024),
)
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)


def _configured_path(variable: str, default: str) -> Path:
    configured = Path(env.str(variable, default=default))
    if configured.is_absolute():
        return configured
    return (BASE_DIR / configured).resolve()


LABARCHIVE_ENV = env.str("LABARCHIVE_ENV", default="development")
SECRET_KEY = env.str(
    "LABARCHIVE_SECRET_KEY",
    default="development-only-insecure-key-change-before-real-data",
)
DEBUG = env.bool("LABARCHIVE_DEBUG", default=False)
ALLOWED_HOSTS = env.list(
    "LABARCHIVE_ALLOWED_HOSTS",
    default=["127.0.0.1", "localhost"],
)
CSRF_TRUSTED_ORIGINS = [
    origin for origin in env.list("LABARCHIVE_CSRF_TRUSTED_ORIGINS", default=[]) if origin
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts",
    "apps.core",
    "apps.projects",
    "apps.documents",
    "apps.expenses",
    "apps.todos",
    "apps.audit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.core.middleware.RequestIDMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.ForcePasswordChangeMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env.str("POSTGRES_DB", default="labarchive"),
        "USER": env.str("POSTGRES_USER", default="labarchive"),
        "PASSWORD": env.str("POSTGRES_PASSWORD", default="labarchive-local-only"),
        "HOST": env.str("POSTGRES_HOST", default="127.0.0.1"),
        "PORT": env.int("POSTGRES_PORT", default=5432),
        "CONN_MAX_AGE": env.int("POSTGRES_CONN_MAX_AGE", default=0),
        "OPTIONS": {"connect_timeout": 5},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "media/"
MEDIA_ROOT = _configured_path("LABARCHIVE_MEDIA_ROOT", "media")
LABARCHIVE_BACKUP_PATH = _configured_path("LABARCHIVE_BACKUP_PATH", ".local/backups")

DATA_UPLOAD_MAX_MEMORY_SIZE = env.int(
    "LABARCHIVE_MAX_UPLOAD_SIZE",
    default=100 * 1024 * 1024,
)
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_PERMISSIONS = 0o640
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o750

AUTH_USER_MODEL = "accounts.User"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "accounts:login"

SESSION_COOKIE_AGE = 12 * 60 * 60
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

LOGIN_MAX_FAILURES = 5
LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60
LOGIN_LOCKOUT_SECONDS = 15 * 60
