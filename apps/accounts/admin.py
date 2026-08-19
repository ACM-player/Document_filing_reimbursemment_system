from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from apps.audit.models import AuditAction
from apps.audit.services import record_audit_event

from .forms import LabArchiveUserChangeForm, LabArchiveUserCreationForm
from .models import User, UserProfile
from .services import change_user_status, reset_temporary_password, sync_staff_flag


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    extra = 0
    fields = ("department", "student_or_staff_id", "phone", "notes")


@admin.register(User)
class LabArchiveUserAdmin(UserAdmin):
    form = LabArchiveUserChangeForm
    add_form = LabArchiveUserCreationForm
    inlines = (UserProfileInline,)
    change_form_template = "admin/accounts/user/change_form.html"
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("个人信息", {"fields": ("display_name", "first_name", "last_name", "email")}),
        (
            "账号生命周期",
            {
                "fields": (
                    "account_status",
                    "must_change_password",
                    "is_active",
                    "is_staff",
                )
            },
        ),
        ("预定义系统角色", {"fields": ("groups",)}),
        ("重要时间", {"fields": ("last_login", "date_joined", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "display_name",
                    "email",
                    "account_status",
                    "password1",
                    "password2",
                ),
            },
        ),
    )
    readonly_fields = (
        "must_change_password",
        "is_active",
        "is_staff",
        "last_login",
        "date_joined",
        "created_at",
        "updated_at",
    )
    list_display = (
        "username",
        "display_name",
        "email",
        "account_status",
        "is_staff",
        "role_names",
    )
    list_filter = ("account_status", "groups", "is_staff")
    search_fields = ("username", "display_name", "email")
    ordering = ("username",)
    filter_horizontal = ("groups",)

    @admin.display(description="系统角色")
    def role_names(self, obj):
        return ", ".join(obj.groups.order_by("name").values_list("name", flat=True))

    def get_urls(self):
        custom_urls = [
            path(
                "<path:object_id>/reset-temporary-password/",
                self.admin_site.admin_view(self.reset_temporary_password_view),
                name="accounts_user_reset_temporary_password",
            )
        ]
        return custom_urls + super().get_urls()

    def reset_temporary_password_link(self, obj):
        url = reverse("admin:accounts_user_reset_temporary_password", args=(obj.pk,))
        return format_html('<a class="button" href="{}">生成一次性临时密码</a>', url)

    def reset_temporary_password_view(self, request, object_id):
        if not request.user.has_perm("accounts.reset_user_password"):
            raise PermissionDenied
        try:
            target_user = User.objects.get(pk=object_id)
        except (User.DoesNotExist, ValueError) as exc:
            raise Http404 from exc

        temporary_password = None
        if request.method == "POST":
            temporary_password = reset_temporary_password(
                user=target_user,
                actor=request.user,
                request=request,
            )

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "original": target_user,
            "title": "生成一次性临时密码",
            "temporary_password": temporary_password,
        }
        response = TemplateResponse(
            request,
            "admin/accounts/user/reset_temporary_password.html",
            context,
        )
        response["Cache-Control"] = "no-store, max-age=0"
        response["Pragma"] = "no-cache"
        return response

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        old_status = None
        requested_status = obj.account_status
        if change:
            old_status = User.objects.only("account_status").get(pk=obj.pk).account_status
            request._labarchive_old_roles = set(
                User.objects.get(pk=obj.pk).groups.values_list("name", flat=True)
            )
            if old_status != requested_status:
                obj.account_status = old_status
        super().save_model(request, obj, form, change)
        if not change:
            record_audit_event(
                action=AuditAction.USER_CREATED,
                request=request,
                actor=request.user,
                subject=obj,
                description="系统管理员创建用户",
                new_value={"account_status": obj.account_status},
            )
        elif old_status != requested_status:
            changed_user = change_user_status(
                user=obj,
                new_status=requested_status,
                actor=request.user,
                request=request,
            )
            obj.account_status = changed_user.account_status
            obj.is_active = changed_user.is_active

    def save_related(self, request, form, formsets, change):
        with transaction.atomic():
            super().save_related(request, form, formsets, change)
            user = form.instance
            sync_staff_flag(user)
            old_roles = getattr(request, "_labarchive_old_roles", set())
            new_roles = set(user.groups.values_list("name", flat=True))
            for role in sorted(new_roles - old_roles):
                record_audit_event(
                    action=AuditAction.ROLE_ASSIGNED,
                    request=request,
                    actor=request.user,
                    subject=user,
                    description="系统管理员分配预定义角色",
                    new_value={"role": role},
                )
            for role in sorted(old_roles - new_roles):
                record_audit_event(
                    action=AuditAction.ROLE_REMOVED,
                    request=request,
                    actor=request.user,
                    subject=user,
                    description="系统管理员移除预定义角色",
                    old_value={"role": role},
                )

    def has_delete_permission(self, request, obj=None):
        return False


try:
    admin.site.unregister(Group)
except admin.sites.NotRegistered:
    pass
