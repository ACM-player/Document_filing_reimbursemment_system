from django.urls import path

from . import views

app_name = "projects"

urlpatterns = [
    path("", views.project_list, name="list"),
    path("create/", views.project_create, name="create"),
    path("<uuid:project_id>/", views.project_detail, name="detail"),
    path("<uuid:project_id>/edit/", views.project_update, name="update"),
    path("<uuid:project_id>/delete/", views.project_delete, name="delete"),
    path("<uuid:project_id>/members/", views.project_members, name="members"),
    path(
        "<uuid:project_id>/members/<uuid:membership_id>/remove/",
        views.project_member_remove,
        name="member_remove",
    ),
    path(
        "<uuid:project_id>/access-requests/submit/",
        views.access_request_submit,
        name="access_submit",
    ),
    path(
        "<uuid:project_id>/access-requests/<uuid:access_request_id>/review/",
        views.access_request_review,
        name="access_review",
    ),
    path(
        "<uuid:project_id>/access-requests/<uuid:access_request_id>/cancel/",
        views.access_request_cancel,
        name="access_cancel",
    ),
]
