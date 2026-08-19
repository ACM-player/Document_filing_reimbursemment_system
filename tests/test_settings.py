import os
import subprocess
import sys
import uuid

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, models


def test_postgresql_is_the_only_configured_database_backend():
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"


def test_phase_three_file_security_defaults_are_centralized():
    assert settings.LABARCHIVE_ALLOWED_UPLOAD_EXTENSIONS == (
        ".pdf",
        ".docx",
        ".xlsx",
        ".png",
        ".jpg",
        ".jpeg",
        ".zip",
    )
    assert settings.LABARCHIVE_MAX_UPLOAD_SIZE > 0
    assert settings.LABARCHIVE_ZIP_MAX_TOTAL_SIZE >= settings.LABARCHIVE_ZIP_MAX_MEMBER_SIZE
    assert settings.LABARCHIVE_ZIP_MAX_MEMBER_SIZE >= settings.LABARCHIVE_MAX_UPLOAD_SIZE
    assert settings.LABARCHIVE_ZIP_MAX_COMPRESSION_RATIO > 0
    assert settings.LABARCHIVE_ZIP_MAX_MEMBERS > 0
    assert settings.LABARCHIVE_OOXML_METADATA_MAX_SIZE > 0
    assert settings.LABARCHIVE_REQUIRE_MALWARE_SCAN is False
    assert settings.LABARCHIVE_STAGING_ROOT.is_absolute()


def test_production_forces_malware_scan_even_if_environment_requests_false():
    environment = os.environ.copy()
    environment.update(
        {
            "DJANGO_SETTINGS_MODULE": "config.settings.production",
            "LABARCHIVE_SECRET_KEY": "production-test-secret-that-is-not-used-for-real-data",
            "LABARCHIVE_REQUIRE_MALWARE_SCAN": "false",
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from django.conf import settings; assert settings.LABARCHIVE_REQUIRE_MALWARE_SCAN",
        ],
        cwd=settings.BASE_DIR,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_custom_user_is_configured_before_first_migration():
    user_model = get_user_model()
    id_field = user_model._meta.get_field("id")

    assert settings.AUTH_USER_MODEL == "accounts.User"
    assert isinstance(id_field, models.UUIDField)
    assert callable(id_field.default)
    assert isinstance(id_field.default(), uuid.UUID)


@pytest.mark.django_db
def test_custom_user_can_be_persisted():
    user_model = get_user_model()
    user = user_model.objects.create_user(
        username="phase-zero-user",
        display_name="Phase Zero",
        password="test-only-password",
    )

    assert isinstance(user.id, uuid.UUID)
    assert str(user) == "Phase Zero"


@pytest.mark.django_db
def test_database_is_postgresql_17_with_page_checksums():
    with connection.cursor() as cursor:
        cursor.execute("SHOW server_version_num")
        server_version_num = int(cursor.fetchone()[0])
        cursor.execute("SHOW data_checksums")
        data_checksums = cursor.fetchone()[0]

    assert 170000 <= server_version_num < 180000
    assert data_checksums == "on"
