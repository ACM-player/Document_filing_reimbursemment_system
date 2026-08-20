from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.projects.models import Project
from apps.projects.permissions import can_view_project, is_project_portal_user

from .forms import DocumentUploadForm, ProjectDocumentCategoryForm
from .models import Document
from .permissions import (
    can_manage_project_document_categories,
    can_soft_delete_document,
    can_upload_documents,
)
from .services import (
    DocumentDownloadError,
    DocumentLifecycleError,
    DocumentUploadError,
    create_project_document_category,
    prepare_document_download,
    recycle_bin_documents_for,
    restore_document,
    soft_delete_document,
    upload_document,
)


def _require_project_portal_user(request):
    """Reject ineligible accounts before resolving a project or document UUID."""
    if not is_project_portal_user(request.user):
        raise PermissionDenied


def _add_validation_error(form, error):
    if hasattr(error, "message_dict"):
        for field, messages_list in error.message_dict.items():
            target = field if field in form.fields else None
            for message in messages_list:
                form.add_error(target, message)
    else:
        for message in error.messages:
            form.add_error(None, message)


@login_required
@require_GET
def document_list(request, project_id):
    _require_project_portal_user(request)
    project = get_object_or_404(Project.objects, pk=project_id)
    if not can_view_project(request.user, project):
        raise PermissionDenied
    documents = list(
        Document.objects.filter(project=project).select_related(
            "category", "file_asset", "uploaded_by"
        )
    )
    return render(
        request,
        "documents/document_list.html",
        {
            "project": project,
            "documents": [
                {"document": item, "can_delete": can_soft_delete_document(request.user, item)}
                for item in documents
            ],
            "can_upload": can_upload_documents(request.user, project),
            "can_manage_categories": can_manage_project_document_categories(request.user, project),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def document_upload(request, project_id):
    _require_project_portal_user(request)
    project = get_object_or_404(Project.objects, pk=project_id)
    if not can_upload_documents(request.user, project):
        raise PermissionDenied
    form = DocumentUploadForm(request.POST or None, request.FILES or None, project=project)
    if request.method == "POST" and form.is_valid():
        try:
            outcome = upload_document(
                actor=request.user,
                project=project,
                category=form.cleaned_data["category"],
                uploaded_file=form.cleaned_data["file"],
                upload_token=form.cleaned_data["upload_token"],
                title=form.cleaned_data["title"],
                description=form.cleaned_data["description"],
                document_date=form.cleaned_data["document_date"],
                http_request=request,
            )
        except DocumentUploadError as error:
            form.add_error("file", str(error))
        except ValidationError as error:
            _add_validation_error(form, error)
        else:
            message = "上传请求已安全重放。" if outcome.is_replay else "文档上传完成。"
            messages.success(request, message)
            return redirect("documents:list", project_id=project.pk)
    return render(
        request,
        "documents/document_upload.html",
        {"project": project, "form": form},
    )


@login_required
@require_http_methods(["GET", "POST"])
def document_category_create(request, project_id):
    _require_project_portal_user(request)
    project = get_object_or_404(Project.objects, pk=project_id)
    if not can_manage_project_document_categories(request.user, project):
        raise PermissionDenied
    form = ProjectDocumentCategoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            create_project_document_category(
                actor=request.user,
                project=project,
                code=form.cleaned_data["code"],
                name=form.cleaned_data["name"],
                sort_order=form.cleaned_data["sort_order"],
                http_request=request,
            )
        except ValidationError as error:
            _add_validation_error(form, error)
        else:
            messages.success(request, "文档分类已创建。")
            return redirect("documents:list", project_id=project.pk)
    return render(
        request,
        "documents/document_category_form.html",
        {"project": project, "form": form},
    )


@login_required
@require_POST
def document_delete(request, project_id, document_id):
    _require_project_portal_user(request)
    project = get_object_or_404(Project.objects, pk=project_id)
    document = get_object_or_404(
        Document.objects.select_related("project"), pk=document_id, project=project
    )
    try:
        soft_delete_document(actor=request.user, document=document, http_request=request)
    except DocumentLifecycleError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "文档已移入回收站，物理文件仍保留。")
    return redirect("documents:list", project_id=project.pk)


@login_required
@require_GET
def recycle_bin(request):
    _require_project_portal_user(request)
    return render(
        request,
        "documents/recycle_bin.html",
        {"documents": recycle_bin_documents_for(request.user)},
    )


@login_required
@require_POST
def document_restore(request, document_id):
    _require_project_portal_user(request)
    document = get_object_or_404(Document.all_objects, pk=document_id, deleted_at__isnull=False)
    project_id = document.project_id
    try:
        restore_document(actor=request.user, document=document, http_request=request)
    except DocumentLifecycleError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "文档已从回收站恢复。")
        return redirect("documents:list", project_id=project_id)
    return redirect("documents:recycle_bin")


@login_required
@require_GET
def document_download(request, document_id):
    _require_project_portal_user(request)
    try:
        prepared = prepare_document_download(
            actor=request.user,
            document_id=document_id,
            http_request=request,
        )
    except DocumentDownloadError as exc:
        raise Http404("文件不存在或当前不可下载。") from exc
    response = FileResponse(
        prepared.file,
        as_attachment=True,
        filename=prepared.filename,
        content_type=prepared.content_type,
    )
    response["Content-Length"] = prepared.file_size
    return response
