from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "actor_username", "object_type", "result")
    list_filter = ("action", "result", "created_at")
    search_fields = ("actor_username", "object_type", "object_id", "description")
    readonly_fields = tuple(field.name for field in AuditLog._meta.fields)
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm("audit.view_auditlog")

    def has_delete_permission(self, request, obj=None):
        return False
