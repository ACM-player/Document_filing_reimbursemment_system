import uuid

from django.conf import settings
from django.db import models


class AuditAction(models.TextChoices):
    LOGIN_SUCCESS = "LOGIN_SUCCESS", "登录成功"
    LOGIN_FAILED = "LOGIN_FAILED", "登录失败"
    LOGOUT = "LOGOUT", "退出登录"
    PASSWORD_CHANGED = "PASSWORD_CHANGED", "用户修改密码"
    PASSWORD_RESET_BY_ADMIN = "PASSWORD_RESET_BY_ADMIN", "管理员重置密码"
    USER_CREATED = "USER_CREATED", "创建用户"
    USER_STATUS_CHANGED = "USER_STATUS_CHANGED", "修改账号状态"
    ROLE_ASSIGNED = "ROLE_ASSIGNED", "分配角色"
    ROLE_REMOVED = "ROLE_REMOVED", "移除角色"
    PROFILE_UPDATED = "PROFILE_UPDATED", "更新个人资料"
    PROJECT_CREATED = "PROJECT_CREATED", "创建项目"
    PROJECT_UPDATED = "PROJECT_UPDATED", "更新项目"
    PROJECT_ARCHIVED = "PROJECT_ARCHIVED", "归档项目"
    PROJECT_SOFT_DELETED = "PROJECT_SOFT_DELETED", "软删除项目"
    PROJECT_MEMBER_ADDED = "PROJECT_MEMBER_ADDED", "添加项目成员"
    PROJECT_MEMBER_UPDATED = "PROJECT_MEMBER_UPDATED", "更新项目成员"
    PROJECT_MEMBER_REMOVED = "PROJECT_MEMBER_REMOVED", "移除项目成员"
    PROJECT_PI_TRANSFERRED = "PROJECT_PI_TRANSFERRED", "更换项目负责人"
    ACCESS_REQUEST_SUBMITTED = "ACCESS_REQUEST_SUBMITTED", "提交项目访问申请"
    ACCESS_REQUEST_APPROVED = "ACCESS_REQUEST_APPROVED", "批准项目访问申请"
    ACCESS_REQUEST_REJECTED = "ACCESS_REQUEST_REJECTED", "拒绝项目访问申请"
    ACCESS_REQUEST_CANCELLED = "ACCESS_REQUEST_CANCELLED", "取消项目访问申请"
    ACCESS_REQUEST_REVOKED = "ACCESS_REQUEST_REVOKED", "撤销项目访问授权"
    ACCESS_REQUEST_EXPIRED = "ACCESS_REQUEST_EXPIRED", "项目访问授权到期"


class AuditResult(models.TextChoices):
    SUCCESS = "SUCCESS", "成功"
    DENIED = "DENIED", "拒绝"
    FAILED = "FAILED", "失败"


class AppendOnlyAuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("Audit records are append-only and cannot be updated.")

    def delete(self):
        raise TypeError("Audit records are append-only and cannot be deleted.")


class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
    )
    actor_username = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=64, choices=AuditAction.choices, db_index=True)
    object_type = models.CharField(max_length=150, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    description = models.TextField(blank=True)
    old_value = models.JSONField(default=dict, blank=True)
    new_value = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    request_id = models.UUIDField(null=True, blank=True, db_index=True)
    result = models.CharField(
        max_length=16,
        choices=AuditResult.choices,
        default=AuditResult.SUCCESS,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = AppendOnlyAuditQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("object_type", "object_id", "created_at"))]
        verbose_name = "审计日志"
        verbose_name_plural = "审计日志"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Audit records are append-only and cannot be updated.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Audit records are append-only and cannot be deleted.")

    def __str__(self) -> str:
        return f"{self.action} @ {self.created_at:%Y-%m-%d %H:%M:%S}"
