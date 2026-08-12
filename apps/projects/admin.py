from django.contrib import admin

from .models import Project, ProjectAccessRequest, ProjectMembership, ProjectType


@admin.register(ProjectType)
class ProjectTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("code", "name")
    ordering = ("sort_order", "name")


class ReadOnlyProjectAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm(f"{self.opts.app_label}.view_{self.opts.model_name}")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Project)
class ProjectAdmin(ReadOnlyProjectAdmin):
    list_display = (
        "project_code",
        "name",
        "status",
        "visibility",
        "principal_investigator",
        "deleted_at",
    )
    list_filter = ("status", "visibility", "project_type", "deleted_at")
    search_fields = ("project_code", "name", "short_name")
    readonly_fields = tuple(field.name for field in Project._meta.fields)

    def get_queryset(self, request):
        return Project.all_objects.select_related("project_type", "principal_investigator")


@admin.register(ProjectMembership)
class ProjectMembershipAdmin(ReadOnlyProjectAdmin):
    list_display = (
        "project",
        "user",
        "role",
        "access_source",
        "source_access_request",
        "expires_at",
        "left_at",
    )
    list_filter = ("role", "access_source", "left_at")
    search_fields = ("project__project_code", "project__name", "user__username")
    readonly_fields = tuple(field.name for field in ProjectMembership._meta.fields)


@admin.register(ProjectAccessRequest)
class ProjectAccessRequestAdmin(ReadOnlyProjectAdmin):
    list_display = ("project", "requester", "status", "requested_at", "expires_at")
    list_filter = ("status", "requested_at")
    search_fields = ("project__project_code", "project__name", "requester__username")
    readonly_fields = tuple(field.name for field in ProjectAccessRequest._meta.fields)
