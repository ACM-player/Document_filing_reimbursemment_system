import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel, UUIDModel


class AccountStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "正常"
    DISABLED = "DISABLED", "临时禁用"
    DEPARTED = "DEPARTED", "已离组"
    ARCHIVED = "ARCHIVED", "已归档"


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    display_name = models.CharField("显示名称", max_length=150, blank=True)
    account_status = models.CharField(
        "账号状态",
        max_length=16,
        choices=AccountStatus.choices,
        default=AccountStatus.ACTIVE,
    )
    must_change_password = models.BooleanField("必须修改密码", default=False)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ("username",)
        verbose_name = "用户"
        verbose_name_plural = "用户"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(account_status=AccountStatus.ACTIVE, is_active=True)
                    | (~Q(account_status=AccountStatus.ACTIVE) & Q(is_active=False))
                ),
                name="accounts_user_status_matches_is_active",
            )
        ]
        permissions = [
            ("reset_user_password", "Can reset user passwords"),
            ("change_user_status", "Can change user lifecycle status"),
            ("assign_system_roles", "Can assign predefined system roles"),
        ]

    def save(self, *args, **kwargs):
        self.is_active = self.account_status == AccountStatus.ACTIVE
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = {*update_fields, "is_active"}
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.display_name or self.username


class UserProfile(UUIDModel, TimeStampedModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    department = models.CharField("院系或部门", max_length=200, blank=True)
    student_or_staff_id = models.CharField("学工号", max_length=100, blank=True)
    phone = models.CharField("联系电话", max_length=50, blank=True)
    notes = models.TextField("管理员备注", blank=True)

    class Meta:
        verbose_name = "用户资料"
        verbose_name_plural = "用户资料"

    def __str__(self) -> str:
        return f"{self.user} 的资料"


class LoginThrottle(UUIDModel):
    username_fingerprint = models.CharField(max_length=64)
    source_ip = models.GenericIPAddressField()
    failure_count = models.PositiveSmallIntegerField(default=0)
    window_started_at = models.DateTimeField()
    locked_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("username_fingerprint", "source_ip"),
                name="accounts_unique_login_throttle_key",
            )
        ]
        indexes = [models.Index(fields=("locked_until", "updated_at"))]
        verbose_name = "登录限制"
        verbose_name_plural = "登录限制"
