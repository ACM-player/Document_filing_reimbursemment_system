import uuid

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, models


def test_postgresql_is_the_only_configured_database_backend():
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"


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
