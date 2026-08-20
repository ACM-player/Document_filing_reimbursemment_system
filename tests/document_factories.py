from uuid import uuid4

from apps.documents.models import (
    Document,
    DocumentCategory,
    FileAsset,
    FileStorageStatus,
)


def make_file_asset(*, uploaded_by, status=FileStorageStatus.AVAILABLE, **kwargs):
    token = uuid4()
    values = {
        "original_filename": f"document-{token}.pdf",
        "stored_filename": f"{token}.pdf",
        "relative_path": f"projects/test/documents/{token}.pdf",
        "declared_mime_type": "application/pdf",
        "detected_mime_type": "application/pdf",
        "file_size": 128,
        "sha256": "a" * 64,
        "storage_status": status,
        "uploaded_by": uploaded_by,
    }
    if status == FileStorageStatus.TEMPORARY:
        values.update(detected_mime_type="", file_size=None, sha256="")
    values.update(kwargs)
    return FileAsset.objects.create(**values)


def make_document(*, project, uploaded_by, category=None, file_asset=None, **kwargs):
    category = category or DocumentCategory.objects.create(
        code=f"GLOBAL-{uuid4()}",
        name=f"全局分类-{uuid4()}",
    )
    file_asset = file_asset or make_file_asset(uploaded_by=uploaded_by)
    return Document.objects.create(
        project=project,
        category=category,
        file_asset=file_asset,
        title="测试项目文档",
        uploaded_by=uploaded_by,
        **kwargs,
    )
