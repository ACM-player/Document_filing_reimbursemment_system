import pytest
from django.contrib import admin
from django.test import RequestFactory

from apps.projects.admin import (
    ProjectAccessRequestAdmin,
    ProjectAdmin,
    ProjectMembershipAdmin,
)
from apps.projects.models import Project, ProjectAccessRequest, ProjectMembership

from .project_factories import make_user

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("admin_class", "model"),
    [
        (ProjectAdmin, Project),
        (ProjectMembershipAdmin, ProjectMembership),
        (ProjectAccessRequestAdmin, ProjectAccessRequest),
    ],
)
def test_project_record_admins_are_read_only(admin_class, model):
    request = RequestFactory().get("/admin/")
    request.user = make_user(f"readonly-admin-{model._meta.model_name}", is_superuser=True)
    model_admin = admin_class(model, admin.site)

    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_change_permission(request) is True
    assert model_admin.has_delete_permission(request) is False
    assert set(model_admin.readonly_fields) == {field.name for field in model._meta.fields}
