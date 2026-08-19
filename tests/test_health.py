import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse


def test_home_page_requires_authentication():
    response = Client().get("/")

    assert response.status_code == 302
    assert response.url == f"{reverse('accounts:login')}?next=/"


@pytest.mark.django_db
def test_authenticated_home_page_identifies_phase_one():
    user = get_user_model().objects.create_user(
        username="phase-one-user",
        password="test-only-password",
    )
    client = Client()
    client.force_login(user)

    response = client.get("/")

    assert response.status_code == 200
    assert "Phase 1" in response.content.decode()


def test_health_endpoint_reports_environment():
    response = Client().get("/health/")

    assert response.status_code == 200
    assert response.json() == {
        "service": "labarchive",
        "status": "ok",
        "environment": settings.LABARCHIVE_ENV,
    }
