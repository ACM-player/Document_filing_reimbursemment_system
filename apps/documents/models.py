import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower

from apps.core.models import SoftDeleteModel, TimeStampedModel, UUIDModel
from apps.projects.models import Project


class FileStorageStatus(models.TextChoices):
    TEMPORARY = "TEMPORARY", "临时"
    QUARANTINED = "QUARANTINED", "已隔离"
    AVAILABLE = "AVAILABLE", "可用"
    MISSING = "MISSING", "物理文件缺失或完整性异常"
    DELETED = "DELETED", "已软删除"


class MalwareScanStatus(models.TextChoices):
    NOT_CONFIGURED = "NOT_CONFIGURED", "未配置"
    PENDING = "PENDING", "待扫描"
    CLEAN = "CLEAN", "扫描通过"
    INFECTED = "INFECTED", "检测到威胁"
    ERROR = "ERROR", "扫描失败"


class FileAsset(UUIDModel, TimeStampedModel):
    original_filename = models.CharField("原始文件名", max_length=255)
    stored_filename = models.CharField("存储文件名", max_length=255, unique=True)
    relative_path = models.CharField("相对存储路径", max_length=500, unique=True)
    declared_mime_type = models.CharField("客户端声明 MIME", max_length=255, blank=True)
    detected_mime_type = models.CharField("服务端检测 MIME", max_length=255, blank=True)
    file_size = models.BigIntegerField("文件大小", null=True, blank=True)
    sha256 = models.CharField("SHA256", max_length=64, blank=True, db_index=True)
    storage_status = models.CharField(
        "存储状态",
        max_length=16,
        choices=FileStorageStatus.choices,
        default=FileStorageStatus.TEMPORARY,
    )
    malware_scan_status = models.CharField(
        "恶意软件扫描状态",
        max_length=20,
        choices=MalwareScanStatus.choices,
        default=MalwareScanStatus.NOT_CONFIGURED,
    )
    status_reason = models.CharField("状态原因代码", max_length=100, blank=True)
    upload_token = models.UUIDField(
        "上传幂等令牌",
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_file_assets",
        verbose_name="上传者",
    )
    quarantined_at = models.DateTimeField("隔离时间", null=True, blank=True)
    deleted_at = models.DateTimeField("删除时间", null=True, blank=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(
                condition=Q(storage_status__in=FileStorageStatus.values),
                name="documents_file_storage_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(malware_scan_status__in=MalwareScanStatus.values),
                name="documents_malware_scan_status_valid",
            ),
            models.CheckConstraint(
                condition=~Q(original_filename=""),
                name="documents_original_filename_not_empty",
            ),
            models.CheckConstraint(
                condition=~Q(stored_filename=""),
                name="documents_stored_filename_not_empty",
            ),
            models.CheckConstraint(
                condition=~Q(relative_path=""),
                name="documents_relative_path_not_empty",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(relative_path__startswith="/")
                    & ~Q(relative_path__contains="\\")
                    & ~Q(relative_path__contains="..")
                    & ~Q(relative_path__regex=r"^[A-Za-z]:")
                    & ~Q(stored_filename__contains="/")
                    & ~Q(stored_filename__contains="\\")
                ),
                name="documents_storage_keys_safe_shape",
            ),
            models.CheckConstraint(
                condition=Q(file_size__isnull=True) | Q(file_size__gt=0),
                name="documents_file_size_positive_when_set",
            ),
            models.CheckConstraint(
                condition=Q(sha256="") | Q(sha256__regex=r"^[0-9a-f]{64}$"),
                name="documents_sha256_blank_or_valid",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(
                        storage_status__in=(
                            FileStorageStatus.AVAILABLE,
                            FileStorageStatus.MISSING,
                            FileStorageStatus.DELETED,
                        )
                    )
                    | (Q(file_size__gt=0) & ~Q(sha256="") & ~Q(detected_mime_type=""))
                ),
                name="documents_final_asset_metadata_complete",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(storage_status=FileStorageStatus.QUARANTINED)
                    | Q(quarantined_at__isnull=False)
                ),
                name="documents_quarantined_asset_has_time",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(storage_status=FileStorageStatus.AVAILABLE)
                    | Q(
                        malware_scan_status__in=(
                            MalwareScanStatus.NOT_CONFIGURED,
                            MalwareScanStatus.CLEAN,
                        )
                    )
                ),
                name="documents_available_scan_state_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(storage_status=FileStorageStatus.DELETED, deleted_at__isnull=False)
                    | (~Q(storage_status=FileStorageStatus.DELETED) & Q(deleted_at__isnull=True))
                ),
                name="documents_deleted_asset_has_time",
            ),
        ]
        verbose_name = "文件资产"
        verbose_name_plural = "文件资产"

    def save(self, *args, **kwargs):
        self.original_filename = self.original_filename.strip()
        self.stored_filename = self.stored_filename.strip()
        self.relative_path = self.relative_path.strip()
        self.declared_mime_type = self.declared_mime_type.strip().lower()
        self.detected_mime_type = self.detected_mime_type.strip().lower()
        self.sha256 = self.sha256.strip().lower()
        self.status_reason = self.status_reason.strip()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.original_filename


class DocumentCategory(UUIDModel, TimeStampedModel):
    project = models.ForeignKey(
        Project,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="document_categories",
        verbose_name="所属项目",
    )
    code = models.CharField("分类代码", max_length=50)
    name = models.CharField("分类名称", max_length=150)
    is_active = models.BooleanField("启用", default=True)
    sort_order = models.PositiveIntegerField("排序", default=0)

    class Meta:
        ordering = ("sort_order", "name", "code")
        constraints = [
            models.UniqueConstraint(
                Lower("code"),
                condition=Q(project__isnull=True),
                name="documents_unique_global_category_code_ci",
            ),
            models.UniqueConstraint(
                F("project"),
                Lower("code"),
                condition=Q(project__isnull=False),
                name="documents_unique_project_category_code_ci",
            ),
            models.UniqueConstraint(
                Lower("name"),
                condition=Q(project__isnull=True),
                name="documents_unique_global_category_name_ci",
            ),
            models.UniqueConstraint(
                F("project"),
                Lower("name"),
                condition=Q(project__isnull=False),
                name="documents_unique_project_category_name_ci",
            ),
            models.CheckConstraint(
                condition=~Q(code=""),
                name="documents_category_code_not_empty",
            ),
            models.CheckConstraint(
                condition=~Q(name=""),
                name="documents_category_name_not_empty",
            ),
        ]
        verbose_name = "文档分类"
        verbose_name_plural = "文档分类"

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        self.name = self.name.strip()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        scope = self.project.project_code if self.project_id else "GLOBAL"
        return f"{scope} / {self.name}"


class DocumentQuerySet(models.QuerySet):
    def active(self):
        return self.filter(deleted_at__isnull=True)


class ActiveDocumentManager(models.Manager.from_queryset(DocumentQuerySet)):
    def get_queryset(self):
        return super().get_queryset().active()


class Document(UUIDModel, TimeStampedModel, SoftDeleteModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name="documents",
        verbose_name="所属项目",
    )
    category = models.ForeignKey(
        DocumentCategory,
        on_delete=models.PROTECT,
        related_name="documents",
        verbose_name="文档分类",
    )
    file_asset = models.OneToOneField(
        FileAsset,
        on_delete=models.PROTECT,
        related_name="document",
        verbose_name="文件资产",
    )
    document_group_id = models.UUIDField("文档组", default=uuid.uuid4, db_index=True)
    version = models.PositiveIntegerField("版本", default=1)
    is_current = models.BooleanField("当前版本", default=True)
    is_final = models.BooleanField("最终版", default=False)
    title = models.CharField("标题", max_length=250)
    description = models.TextField("说明", blank=True)
    document_date = models.DateField("文档日期", null=True, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_documents",
        verbose_name="上传者",
    )

    objects = ActiveDocumentManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ("-created_at", "title")
        constraints = [
            models.UniqueConstraint(
                fields=("document_group_id", "version"),
                name="documents_unique_group_version",
            ),
            models.UniqueConstraint(
                fields=("document_group_id",),
                condition=Q(deleted_at__isnull=True, is_current=True),
                name="documents_unique_active_current_version",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1),
                name="documents_version_positive",
            ),
            models.CheckConstraint(
                condition=~Q(title=""),
                name="documents_title_not_empty",
            ),
        ]
        verbose_name = "项目文档"
        verbose_name_plural = "项目文档"

    def clean(self):
        super().clean()
        errors = {}
        if self.project_id and self.category_id:
            category = self.category
            if category.project_id is not None and category.project_id != self.project_id:
                errors["category"] = "项目文档只能使用全局分类或本项目分类。"
            if self._state.adding and not category.is_active:
                errors["category"] = "不能为新文档使用已停用分类。"
        if self.file_asset_id and self.uploaded_by_id:
            if self.file_asset.uploaded_by_id != self.uploaded_by_id:
                errors["file_asset"] = "文档上传者必须与文件资产上传者一致。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.title = self.title.strip()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.project.project_code} / {self.title} / v{self.version}"
