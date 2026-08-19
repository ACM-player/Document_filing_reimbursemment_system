from django.contrib import admin
from django.urls import include, path

from apps.core.views import health, home

urlpatterns = [
    path("", home, name="home"),
    path("health/", health, name="health"),
    path("accounts/", include("apps.accounts.urls")),
    path("admin/", admin.site.urls),
]
