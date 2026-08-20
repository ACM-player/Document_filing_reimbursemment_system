from django.contrib import admin
from django.urls import include, path

from apps.core.views import health, home

urlpatterns = [
    path("", home, name="home"),
    path("health/", health, name="health"),
    path("accounts/", include("apps.accounts.urls")),
    path("projects/", include("apps.projects.urls")),
    path("documents/", include("apps.documents.urls")),
    path("admin/", admin.site.urls),
]
