from django.conf import settings
from django.test import Client


def test_home_page_identifies_phase_zero():
    response = Client().get("/")

    assert response.status_code == 200
    assert "Phase 0" in response.content.decode()


def test_health_endpoint_reports_environment():
    response = Client().get("/health/")

    assert response.status_code == 200
    assert response.json() == {
        "service": "labarchive",
        "status": "ok",
        "environment": settings.LABARCHIVE_ENV,
    }
