from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class LabArchiveUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("LabArchive", {"fields": ("display_name", "created_at", "updated_at")}),
    )
    readonly_fields = ("created_at", "updated_at")
    list_display = ("username", "display_name", "email", "is_active", "is_staff")
