from apps.projects.models import ProjectRole, ProjectStatus
from apps.projects.permissions import (
    can_upload_project_files,
    can_view_project,
    is_system_admin,
    project_role_for,
)

from .models import Document, FileStorageStatus


def can_manage_global_document_categories(user) -> bool:
    return is_system_admin(user)


def can_manage_project_document_categories(user, project) -> bool:
    if project.deleted_at is not None or project.status == ProjectStatus.ARCHIVED:
        return False
    if is_system_admin(user):
        return True
    return project_role_for(user, project) in {ProjectRole.PI, ProjectRole.MANAGER}


def can_upload_documents(user, project) -> bool:
    return can_upload_project_files(user, project)


def can_view_document(user, document: Document) -> bool:
    return document.deleted_at is None and can_view_project(user, document.project)


def can_download_document(user, document: Document) -> bool:
    return bool(
        can_view_document(user, document)
        and document.file_asset.storage_status == FileStorageStatus.AVAILABLE
        and document.file_asset.deleted_at is None
    )


def can_edit_document(user, document: Document) -> bool:
    project = document.project
    if document.deleted_at is not None or not can_view_project(user, project):
        return False
    if project.status == ProjectStatus.ARCHIVED:
        return False
    if is_system_admin(user):
        return True
    role = project_role_for(user, project)
    if role in {ProjectRole.PI, ProjectRole.MANAGER}:
        return True
    return role == ProjectRole.MEMBER and document.uploaded_by_id == user.pk


def can_soft_delete_document(user, document: Document) -> bool:
    return can_edit_document(user, document)


def can_restore_document(user, document: Document) -> bool:
    project = document.project
    if document.deleted_at is None or project.deleted_at is not None:
        return False
    if project.status == ProjectStatus.ARCHIVED:
        return False
    if is_system_admin(user):
        return True
    return project_role_for(user, project) in {ProjectRole.PI, ProjectRole.MANAGER}
