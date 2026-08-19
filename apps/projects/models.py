from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower

from apps.core.models import SoftDeleteModel, TimeStampedModel, UUIDModel


class ProjectStatus(models.TextChoices):
    PLANNING = "PLANNING", "筹备"
    ACTIVE = "ACTIVE", "进行中"
    PAUSED = "PAUSED", "暂停"
    COMPLETED = "COMPLETED", "已完成"
    ARCHIVED = "ARCHIVED", "已归档"


class ProjectVisibility(models.TextChoices):
    INTERNAL = "INTERNAL", "课题组内部可见"
    RESTRICTED = "RESTRICTED", "受限项目"


class ProjectRole(models.TextChoices):
    PI = "PI", "项目负责人"
    MANAGER = "MANAGER", "项目管理员"
    MEMBER = "MEMBER", "项目成员"
    VIEWER = "VIEWER", "只读成员"


class MembershipAccessSource(models.TextChoices):
    DIRECT = "DIRECT", "直接分配"
    APPROVED_REQUEST = "APPROVED_REQUEST", "访问申请获批"


class AccessRequestStatus(models.TextChoices):
    PENDING = "PENDING", "待处理"
    APPROVED = "APPROVED", "已批准"
    REJECTED = "REJECTED", "已拒绝"
    CANCELLED = "CANCELLED", "已取消或撤销"
    EXPIRED = "EXPIRED", "已到期"


class ProjectType(UUIDModel, TimeStampedModel):
    code = models.CharField("类型代码", max_length=50, unique=True)
    name = models.CharField("类型名称", max_length=150)
    is_active = models.BooleanField("启用", default=True)
    sort_order = models.PositiveIntegerField("排序", default=0)

    class Meta:
        ordering = ("sort_order", "name", "code")
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                condition=Q(is_active=True),
                name="projects_unique_active_type_name_ci",
            ),
            models.CheckConstraint(
                condition=~Q(code=""),
                name="projects_project_type_code_not_empty",
            ),
            models.CheckConstraint(
                condition=~Q(name=""),
                name="projects_project_type_name_not_empty",
            ),
        ]
        verbose_name = "项目类型"
        verbose_name_plural = "项目类型"

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        self.name = self.name.strip()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name}（{self.code}）"


class ProjectQuerySet(models.QuerySet):
    def active(self):
        return self.filter(deleted_at__isnull=True)


class ActiveProjectManager(models.Manager.from_queryset(ProjectQuerySet)):
    def get_queryset(self):
        return super().get_queryset().active()


class Project(UUIDModel, TimeStampedModel, SoftDeleteModel):
    project_code = models.CharField("项目编号", max_length=100, unique=True)
    name = models.CharField("项目名称", max_length=250)
    short_name = models.CharField("项目简称", max_length=150, blank=True)
    project_type = models.ForeignKey(
        ProjectType,
        on_delete=models.PROTECT,
        related_name="projects",
        verbose_name="项目类型",
    )
    status = models.CharField(
        "项目状态",
        max_length=16,
        choices=ProjectStatus.choices,
        default=ProjectStatus.PLANNING,
    )
    visibility = models.CharField(
        "可见性",
        max_length=16,
        choices=ProjectVisibility.choices,
        default=ProjectVisibility.INTERNAL,
    )
    principal_investigator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="principal_projects",
        verbose_name="项目负责人",
    )
    start_date = models.DateField("开始日期", null=True, blank=True)
    end_date = models.DateField("结束日期", null=True, blank=True)
    description = models.TextField("项目说明", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_projects",
        verbose_name="创建人",
    )

    objects = ActiveProjectManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ("-created_at", "project_code")
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=ProjectStatus.values),
                name="projects_project_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(visibility__in=ProjectVisibility.values),
                name="projects_project_visibility_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(start_date__isnull=True)
                    | Q(end_date__isnull=True)
                    | Q(end_date__gte=F("start_date"))
                ),
                name="projects_project_dates_valid",
            ),
            models.CheckConstraint(
                condition=~Q(project_code=""),
                name="projects_project_code_not_empty",
            ),
            models.CheckConstraint(
                condition=~Q(name=""),
                name="projects_project_name_not_empty",
            ),
        ]
        permissions = [
            ("archive_project", "Can formally archive projects"),
            ("transfer_project_pi", "Can transfer project principal investigator"),
            ("soft_delete_project", "Can soft delete projects"),
        ]
        verbose_name = "项目"
        verbose_name_plural = "项目"

    def save(self, *args, **kwargs):
        self.project_code = self.project_code.strip()
        self.name = self.name.strip()
        self.short_name = self.short_name.strip()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.project_code} · {self.name}"


class ProjectMembership(UUIDModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name="memberships",
        verbose_name="项目",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="project_memberships",
        verbose_name="用户",
    )
    role = models.CharField("项目角色", max_length=16, choices=ProjectRole.choices)
    access_source = models.CharField(
        "授权来源",
        max_length=24,
        choices=MembershipAccessSource.choices,
        default=MembershipAccessSource.DIRECT,
    )
    source_access_request = models.OneToOneField(
        "ProjectAccessRequest",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="granted_membership",
        verbose_name="来源访问申请",
    )
    joined_at = models.DateTimeField("加入时间", auto_now_add=True)
    left_at = models.DateTimeField("离开时间", null=True, blank=True)
    expires_at = models.DateTimeField("到期时间", null=True, blank=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ("project", "role", "joined_at")
        constraints = [
            models.UniqueConstraint(
                fields=("project", "user"),
                condition=Q(left_at__isnull=True),
                name="projects_unique_active_membership",
            ),
            models.UniqueConstraint(
                fields=("project",),
                condition=Q(role=ProjectRole.PI, left_at__isnull=True),
                name="projects_unique_active_pi",
            ),
            models.CheckConstraint(
                condition=Q(role__in=ProjectRole.values),
                name="projects_membership_role_valid",
            ),
            models.CheckConstraint(
                condition=Q(access_source__in=MembershipAccessSource.values),
                name="projects_membership_source_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        access_source=MembershipAccessSource.DIRECT,
                        source_access_request__isnull=True,
                        expires_at__isnull=True,
                    )
                    | Q(
                        access_source=MembershipAccessSource.APPROVED_REQUEST,
                        source_access_request__isnull=False,
                        role=ProjectRole.VIEWER,
                    )
                ),
                name="projects_membership_grant_shape_valid",
            ),
            models.CheckConstraint(
                condition=Q(left_at__isnull=True) | Q(left_at__gte=F("joined_at")),
                name="projects_membership_left_after_joined",
            ),
            models.CheckConstraint(
                condition=Q(expires_at__isnull=True) | Q(expires_at__gt=F("joined_at")),
                name="projects_membership_expires_after_joined",
            ),
        ]
        verbose_name = "项目成员"
        verbose_name_plural = "项目成员"

    def clean(self):
        super().clean()
        errors = {}

        if self.project_id and self.user_id and self.left_at is None:
            project = self.project
            is_canonical_pi = self.user_id == project.principal_investigator_id
            if (self.role == ProjectRole.PI) != is_canonical_pi:
                errors["role"] = "PI 成员记录必须且只能属于项目的规范负责人。"

        if self.source_access_request_id:
            source_request = self.source_access_request
            if self.project_id and source_request.project_id != self.project_id:
                errors["source_access_request"] = "来源申请必须属于同一项目。"
            if self.user_id and source_request.requester_id != self.user_id:
                errors["source_access_request"] = "来源申请必须属于同一用户。"
            if source_request.expires_at != self.expires_at:
                errors["expires_at"] = "成员授权到期时间必须与来源申请一致。"
            if self.left_at is None and source_request.status != AccessRequestStatus.APPROVED:
                errors["source_access_request"] = "活动的申请授权必须对应已批准申请。"

        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.project} / {self.user} / {self.get_role_display()}"


class ProjectAccessRequest(UUIDModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name="access_requests",
        verbose_name="项目",
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="project_access_requests",
        verbose_name="申请人",
    )
    reason = models.TextField("申请理由")
    status = models.CharField(
        "申请状态",
        max_length=16,
        choices=AccessRequestStatus.choices,
        default=AccessRequestStatus.PENDING,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reviewed_project_access_requests",
        verbose_name="审核人",
    )
    review_note = models.TextField("审核说明", blank=True)
    requested_at = models.DateTimeField("申请时间", auto_now_add=True)
    reviewed_at = models.DateTimeField("处理时间", null=True, blank=True)
    expires_at = models.DateTimeField("访问到期时间", null=True, blank=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ("-requested_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("project", "requester"),
                condition=Q(status=AccessRequestStatus.PENDING),
                name="projects_unique_pending_access_request",
            ),
            models.CheckConstraint(
                condition=Q(status__in=AccessRequestStatus.values),
                name="projects_access_request_status_valid",
            ),
            models.CheckConstraint(
                condition=~Q(reason=""),
                name="projects_access_request_reason_not_empty",
            ),
            models.CheckConstraint(
                condition=(~Q(status=AccessRequestStatus.REJECTED) | ~Q(review_note="")),
                name="projects_rejected_request_has_note",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status=AccessRequestStatus.PENDING,
                        reviewed_by__isnull=True,
                        reviewed_at__isnull=True,
                    )
                    | ~Q(status=AccessRequestStatus.PENDING)
                ),
                name="projects_pending_request_unreviewed",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(
                        status__in=(
                            AccessRequestStatus.APPROVED,
                            AccessRequestStatus.REJECTED,
                        )
                    )
                    | Q(reviewed_by__isnull=False, reviewed_at__isnull=False)
                ),
                name="projects_reviewed_request_has_reviewer",
            ),
        ]
        verbose_name = "项目访问申请"
        verbose_name_plural = "项目访问申请"

    def save(self, *args, **kwargs):
        self.reason = self.reason.strip()
        self.review_note = self.review_note.strip()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.project} / {self.requester} / {self.get_status_display()}"
