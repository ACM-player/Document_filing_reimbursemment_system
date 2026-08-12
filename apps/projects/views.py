from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from .forms import (
    AccessRequestForm,
    AccessReviewForm,
    ProjectCreateForm,
    ProjectMemberForm,
    ProjectUpdateForm,
)
from .models import AccessRequestStatus, Project, ProjectAccessRequest, ProjectMembership
from .permissions import (
    active_membership_for,
    can_manage_members,
    can_view_project,
    catalog_projects_for,
    editable_project_fields,
    is_project_portal_user,
    is_system_admin,
    valid_memberships,
)
from .services import (
    cancel_or_revoke_access_request,
    create_project,
    expire_access_grants,
    remove_project_member,
    review_access_request,
    set_project_member,
    soft_delete_project,
    submit_access_request,
    update_project,
)


def _add_validation_error(form, error):
    if hasattr(error, "message_dict"):
        for field, messages_list in error.message_dict.items():
            target = field if field in form.fields else None
            for message in messages_list:
                form.add_error(target, message)
    else:
        for message in error.messages:
            form.add_error(None, message)


def _require_project_portal_user(request):
    """Reject ineligible accounts before resolving a project UUID."""
    if not is_project_portal_user(request.user):
        raise PermissionDenied


def _project_detail_context(request, project, *, review_forms=None):
    full_access = can_view_project(request.user, project)
    membership = active_membership_for(request.user, project)
    can_manage = can_manage_members(request.user, project)
    context = {
        "project": project,
        "full_access": full_access,
        "membership": membership,
        "pending_request": ProjectAccessRequest.objects.filter(
            project=project,
            requester=request.user,
            status=AccessRequestStatus.PENDING,
        ).first(),
        "access_form": AccessRequestForm(),
        "can_edit": bool(editable_project_fields(request.user, project)),
        "can_manage_members": can_manage,
        "is_system_admin": is_system_admin(request.user),
    }
    if can_manage:
        managed_requests = ProjectAccessRequest.objects.filter(
            project=project,
            status__in=(AccessRequestStatus.PENDING, AccessRequestStatus.APPROVED),
        ).select_related("requester")
        context["managed_requests"] = [
            (item, (review_forms or {}).get(item.pk, AccessReviewForm()))
            for item in managed_requests
        ]
        context["memberships"] = valid_memberships().filter(project=project).select_related("user")
    return context


@login_required
def project_list(request):
    _require_project_portal_user(request)
    expire_access_grants(user=request.user)
    system_admin = is_system_admin(request.user)
    entries = []
    for project in catalog_projects_for(request.user):
        entries.append(
            {
                "project": project,
                "can_view": can_view_project(request.user, project),
                "membership": active_membership_for(request.user, project),
            }
        )
    return render(
        request,
        "projects/project_list.html",
        {"entries": entries, "is_system_admin": system_admin},
    )


@login_required
def project_detail(request, project_id):
    _require_project_portal_user(request)
    project = get_object_or_404(
        Project.objects.select_related("project_type", "principal_investigator"),
        pk=project_id,
    )
    expire_access_grants(project=project)
    return render(
        request, "projects/project_detail.html", _project_detail_context(request, project)
    )


@login_required
@require_http_methods(["GET", "POST"])
def project_create(request):
    _require_project_portal_user(request)
    form = ProjectCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            project = create_project(
                actor=request.user,
                cleaned_data=form.cleaned_data,
                http_request=request,
            )
        except ValidationError as error:
            _add_validation_error(form, error)
        else:
            messages.success(request, "项目已创建，你已成为项目负责人。")
            return redirect("projects:detail", project_id=project.pk)
    return render(request, "projects/project_form.html", {"form": form, "title": "创建项目"})


@login_required
@require_http_methods(["GET", "POST"])
def project_update(request, project_id):
    _require_project_portal_user(request)
    project = get_object_or_404(Project.objects, pk=project_id)
    if not editable_project_fields(request.user, project):
        raise PermissionDenied
    form = ProjectUpdateForm(request.POST or None, instance=project, actor=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            project = update_project(
                actor=request.user,
                project=project,
                cleaned_data=form.cleaned_data,
                http_request=request,
            )
        except ValidationError as error:
            _add_validation_error(form, error)
        else:
            messages.success(request, "项目信息已更新。")
            return redirect("projects:detail", project_id=project.pk)
    return render(request, "projects/project_form.html", {"form": form, "title": "编辑项目"})


@login_required
@require_http_methods(["GET", "POST"])
def project_members(request, project_id):
    _require_project_portal_user(request)
    project = get_object_or_404(Project.objects, pk=project_id)
    if not can_manage_members(request.user, project):
        raise PermissionDenied
    expire_access_grants(project=project)
    form = ProjectMemberForm(request.POST or None, project=project)
    if request.method == "POST" and form.is_valid():
        try:
            set_project_member(
                actor=request.user,
                project=project,
                user=form.cleaned_data["user"],
                role=form.cleaned_data["role"],
                http_request=request,
            )
        except ValidationError as error:
            _add_validation_error(form, error)
        else:
            messages.success(request, "项目成员角色已保存。")
            return redirect("projects:members", project_id=project.pk)
    memberships = valid_memberships().filter(project=project).select_related("user")
    return render(
        request,
        "projects/project_members.html",
        {"project": project, "form": form, "memberships": memberships},
    )


@login_required
@require_POST
def project_member_remove(request, project_id, membership_id):
    _require_project_portal_user(request)
    project = get_object_or_404(Project.objects, pk=project_id)
    if not can_manage_members(request.user, project):
        raise PermissionDenied
    membership = get_object_or_404(ProjectMembership, pk=membership_id, project=project)
    try:
        remove_project_member(
            actor=request.user,
            membership=membership,
            http_request=request,
        )
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
    else:
        messages.success(request, "项目成员已移除。")
    if membership.user_id == request.user.pk:
        return redirect("projects:detail", project_id=project.pk)
    return redirect("projects:members", project_id=project.pk)


@login_required
@require_POST
def access_request_submit(request, project_id):
    _require_project_portal_user(request)
    project = get_object_or_404(Project.objects, pk=project_id)
    form = AccessRequestForm(request.POST)
    if form.is_valid():
        try:
            submit_access_request(
                actor=request.user,
                project=project,
                reason=form.cleaned_data["reason"],
                http_request=request,
            )
        except ValidationError as error:
            messages.error(request, "; ".join(error.messages))
        else:
            messages.success(request, "访问申请已提交。")
    else:
        messages.error(request, "请填写有效的访问用途。")
    return redirect("projects:detail", project_id=project.pk)


@login_required
@require_POST
def access_request_review(request, project_id, access_request_id):
    _require_project_portal_user(request)
    project = get_object_or_404(Project.objects, pk=project_id)
    if not can_manage_members(request.user, project):
        raise PermissionDenied
    access_request = get_object_or_404(
        ProjectAccessRequest,
        pk=access_request_id,
        project=project,
    )
    form = AccessReviewForm(request.POST)
    if form.is_valid():
        try:
            review_access_request(
                actor=request.user,
                access_request=access_request,
                approve=form.cleaned_data["decision"] == "approve",
                review_note=form.cleaned_data["review_note"],
                expires_at=form.cleaned_data["expires_at"],
                http_request=request,
            )
        except ValidationError as error:
            _add_validation_error(form, error)
        else:
            messages.success(request, "访问申请已处理。")
            return redirect("projects:detail", project_id=project.pk)
    return render(
        request,
        "projects/project_detail.html",
        _project_detail_context(request, project, review_forms={access_request.pk: form}),
    )


@login_required
@require_POST
def access_request_cancel(request, project_id, access_request_id):
    _require_project_portal_user(request)
    project = get_object_or_404(Project.objects, pk=project_id)
    access_request = get_object_or_404(
        ProjectAccessRequest,
        pk=access_request_id,
        project=project,
    )
    try:
        cancel_or_revoke_access_request(
            actor=request.user,
            access_request=access_request,
            http_request=request,
        )
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
    else:
        messages.success(request, "访问申请或授权已取消。")
    return redirect("projects:detail", project_id=project.pk)


@login_required
@require_POST
def project_delete(request, project_id):
    _require_project_portal_user(request)
    project = get_object_or_404(Project.objects, pk=project_id)
    if not is_system_admin(request.user):
        raise PermissionDenied
    deleted_project = soft_delete_project(
        actor=request.user,
        project=project,
        http_request=request,
    )
    messages.success(request, f"项目 {deleted_project.project_code} 已移入软删除状态。")
    return redirect(reverse("projects:list"))
