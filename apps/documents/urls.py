from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path("recycle-bin/", views.recycle_bin, name="recycle_bin"),
    path(
        "recycle-bin/<uuid:document_id>/restore/",
        views.document_restore,
        name="restore",
    ),
    path("projects/<uuid:project_id>/", views.document_list, name="list"),
    path("projects/<uuid:project_id>/upload/", views.document_upload, name="upload"),
    path(
        "projects/<uuid:project_id>/categories/create/",
        views.document_category_create,
        name="category_create",
    ),
    path(
        "projects/<uuid:project_id>/<uuid:document_id>/delete/",
        views.document_delete,
        name="delete",
    ),
    path("<uuid:document_id>/download/", views.document_download, name="download"),
]
