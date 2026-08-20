import base64
import hashlib
import zipfile
from io import BytesIO
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.constants import (
    LAB_MEMBER_GROUP,
    REIMBURSEMENT_ADMIN_GROUP,
    SYSTEM_ADMIN_GROUP,
)
from apps.audit.models import AuditAction, AuditLog
from apps.documents.models import Document, DocumentCategory, FileStorageStatus
from apps.projects.models import ProjectMembership, ProjectRole, ProjectStatus, ProjectVisibility

from .project_factories import make_project, make_user

pytestmark = pytest.mark.django_db

PDF_BYTES = b"%PDF-1.7\n1 0 obj<</Type/Catalog>>endobj\n%%EOF\n"
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
JPEG_BYTES = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAEf/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9oADAMBAAIAAwAAABD/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/EB//xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/EB//xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/EB//2Q=="
)


def _zip_bytes(members):
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return output.getvalue()


def _docx_bytes():
    return _zip_bytes(
        {
            "[Content_Types].xml": (
                '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                'package/2006/content-types"><Override PartName="/word/document.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.'
                'document.main+xml"/></Types>'
            ),
            "_rels/.rels": '<Relationships xmlns="urn:test"/>',
            "word/document.xml": '<w:document xmlns:w="urn:test"><w:body/></w:document>',
        }
    )


def _xlsx_bytes():
    return _zip_bytes(
        {
            "[Content_Types].xml": (
                '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                'package/2006/content-types"><Override PartName="/xl/workbook.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.'
                'sheet.main+xml"/></Types>'
            ),
            "_rels/.rels": '<Relationships xmlns="urn:test"/>',
            "xl/workbook.xml": '<workbook xmlns="urn:test"/>',
        }
    )


REAL_SAMPLES = (
    ("evidence.pdf", PDF_BYTES, "application/pdf"),
    (
        "record.docx",
        _docx_bytes(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    (
        "ledger.xlsx",
        _xlsx_bytes(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    ("figure.png", PNG_BYTES, "image/png"),
    ("photo.jpeg", JPEG_BYTES, "image/jpeg"),
    ("bundle.zip", _zip_bytes({"readme.txt": b"phase-three"}), "application/zip"),
)


@pytest.fixture
def page_context(tmp_path, settings):
    media_root = tmp_path / "media"
    settings.MEDIA_ROOT = media_root
    settings.LABARCHIVE_STAGING_ROOT = media_root / ".staging"
    pi = make_user("document-page-pi")
    project = make_project(pi=pi, code="DOCUMENT-PAGE")
    category = DocumentCategory.objects.create(
        project=project,
        code="EVIDENCE",
        name="验收材料",
    )
    client = Client()
    client.force_login(pi)
    return client, pi, project, category


def _upload(client, project, category, filename, content, content_type, *, token=None):
    return client.post(
        reverse("documents:upload", args=(project.pk,)),
        {
            "upload_token": token or uuid4(),
            "category": category.pk,
            "title": f"样本 {filename}",
            "description": "Phase 3 CP7 真实格式样本",
            "document_date": "2026-08-20",
            "file": SimpleUploadedFile(filename, content, content_type=content_type),
        },
    )


def _response_bytes(response):
    return b"".join(response.streaming_content)


def test_document_pages_require_login(page_context):
    _, _, project, _ = page_context

    response = Client().get(reverse("documents:list", args=(project.pk,)))

    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))


@pytest.mark.parametrize(("filename", "content", "content_type"), REAL_SAMPLES)
def test_real_samples_upload_list_download_and_sha256(
    page_context,
    filename,
    content,
    content_type,
):
    client, _, project, category = page_context

    response = _upload(client, project, category, filename, content, content_type)

    assert response.status_code == 302
    assert response.url == reverse("documents:list", args=(project.pk,))
    document = Document.objects.select_related("file_asset").get()
    assert document.file_asset.storage_status == FileStorageStatus.AVAILABLE
    assert document.file_asset.sha256 == hashlib.sha256(content).hexdigest()

    list_response = client.get(reverse("documents:list", args=(project.pk,)))
    assert list_response.status_code == 200
    assert document.title in list_response.content.decode()
    download = client.get(reverse("documents:download", args=(document.pk,)))
    assert download.status_code == 200
    assert _response_bytes(download) == content


def test_upload_token_replay_is_idempotent_through_page(page_context):
    client, _, project, category = page_context
    token = uuid4()

    first = _upload(
        client, project, category, "first.pdf", PDF_BYTES, "application/pdf", token=token
    )
    replay = _upload(
        client,
        project,
        category,
        "second.pdf",
        b"%PDF-1.7\ndifferent\n%%EOF\n",
        "application/pdf",
        token=token,
    )

    assert first.status_code == replay.status_code == 302
    assert Document.all_objects.count() == 1
    assert "安全重放" in list(replay.wsgi_request._messages)[-1].message


def test_invalid_upload_keeps_token_and_shows_safe_failure(page_context):
    client, _, project, category = page_context
    token = uuid4()

    response = _upload(
        client,
        project,
        category,
        "fake.pdf",
        b"not-a-pdf",
        "application/pdf",
        token=token,
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert str(token) in content
    assert "文件内容与扩展名或必要结构不一致" in content


def test_category_creation_is_project_scoped_and_audited(page_context):
    client, _, project, _ = page_context

    response = client.post(
        reverse("documents:category_create", args=(project.pk,)),
        {"code": " raw-data ", "name": " 原始数据 ", "sort_order": 10},
    )

    assert response.status_code == 302
    category = DocumentCategory.objects.get(project=project, code="RAW-DATA")
    assert category.name == "原始数据"
    assert category.sort_order == 10
    assert AuditLog.objects.filter(
        action=AuditAction.PROJECT_UPDATED,
        object_id=str(project.pk),
        description="创建项目文档分类",
    ).exists()


def test_member_can_upload_and_delete_only_own_document(page_context):
    client, pi, project, category = page_context
    member = make_user("document-page-member")
    ProjectMembership.objects.create(project=project, user=member, role=ProjectRole.MEMBER)
    client.force_login(member)
    assert (
        _upload(client, project, category, "owned.pdf", PDF_BYTES, "application/pdf").status_code
        == 302
    )
    own = Document.objects.get(uploaded_by=member)

    client.force_login(pi)
    assert (
        _upload(client, project, category, "pi.pdf", PDF_BYTES, "application/pdf").status_code
        == 302
    )
    pi_document = Document.objects.get(uploaded_by=pi)

    client.force_login(member)
    denied = client.post(reverse("documents:delete", args=(project.pk, pi_document.pk)))
    assert denied.status_code == 403
    deleted = client.post(reverse("documents:delete", args=(project.pk, own.pk)))
    assert deleted.status_code == 302
    own.refresh_from_db()
    assert own.deleted_at is not None


def test_viewer_and_internal_reader_are_read_only(page_context):
    _, _, project, _ = page_context
    reader = make_user("document-page-reader")
    viewer = make_user("document-page-viewer")
    restricted = make_project(
        pi=project.principal_investigator,
        project_type=project.project_type,
        code="DOCUMENT-RESTRICTED",
        visibility=ProjectVisibility.RESTRICTED,
    )
    ProjectMembership.objects.create(project=restricted, user=viewer, role=ProjectRole.VIEWER)
    for actor, target in ((reader, project), (viewer, restricted)):
        client = Client()
        client.force_login(actor)
        assert client.get(reverse("documents:list", args=(target.pk,))).status_code == 200
        assert client.get(reverse("documents:upload", args=(target.pk,))).status_code == 403
        assert (
            client.get(reverse("documents:category_create", args=(target.pk,))).status_code == 403
        )


def test_restricted_idor_and_reimbursement_role_do_not_grant_access(page_context):
    _, pi, project, category = page_context
    restricted = make_project(
        pi=pi,
        project_type=project.project_type,
        code="DOCUMENT-IDOR",
        visibility=ProjectVisibility.RESTRICTED,
    )
    restricted_category = DocumentCategory.objects.create(
        project=restricted, code="IDOR", name="私密"
    )
    owner = Client()
    owner.force_login(pi)
    _upload(owner, restricted, restricted_category, "private.pdf", PDF_BYTES, "application/pdf")
    document = Document.objects.get(project=restricted)

    for username, group_name in (
        ("document-outsider", None),
        ("document-reimbursement", REIMBURSEMENT_ADMIN_GROUP),
    ):
        actor = make_user(username)
        if group_name:
            actor.groups.add(Group.objects.get(name=group_name))
        client = Client()
        client.force_login(actor)
        assert client.get(reverse("documents:list", args=(restricted.pk,))).status_code == 403
        assert client.get(reverse("documents:download", args=(document.pk,))).status_code == 404


def test_system_admin_without_lab_group_can_manage_documents(page_context):
    owner, _, project, category = page_context
    _upload(owner, project, category, "admin.pdf", PDF_BYTES, "application/pdf")
    document = Document.objects.get()
    admin = make_user("document-system-admin")
    admin.groups.add(Group.objects.get(name=SYSTEM_ADMIN_GROUP))
    admin.groups.remove(Group.objects.get(name=LAB_MEMBER_GROUP))
    client = Client()
    client.force_login(admin)

    assert client.get(reverse("documents:list", args=(project.pk,))).status_code == 200
    assert client.get(reverse("documents:upload", args=(project.pk,))).status_code == 200
    assert (
        client.post(reverse("documents:delete", args=(project.pk, document.pk))).status_code == 302
    )
    assert client.get(reverse("documents:recycle_bin")).status_code == 200


def test_recycle_bin_scope_and_restore_revalidates_physical_file(page_context):
    client, pi, project, category = page_context
    _upload(client, project, category, "restore.pdf", PDF_BYTES, "application/pdf")
    document = Document.objects.get()
    client.post(reverse("documents:delete", args=(project.pk, document.pk)))

    recycle = client.get(reverse("documents:recycle_bin"))
    assert recycle.status_code == 200
    assert document.title in recycle.content.decode()
    restored = client.post(reverse("documents:restore", args=(document.pk,)))
    assert restored.status_code == 302
    document.refresh_from_db()
    document.file_asset.refresh_from_db()
    assert document.deleted_at is None
    assert document.file_asset.storage_status == FileStorageStatus.AVAILABLE

    member = make_user("document-restore-member")
    ProjectMembership.objects.create(project=project, user=member, role=ProjectRole.MEMBER)
    client.force_login(member)
    assert document.title not in client.get(reverse("documents:recycle_bin")).content.decode()


def test_archived_is_read_only_and_soft_deleted_project_is_hidden(page_context):
    client, _, project, category = page_context
    _upload(client, project, category, "archived.pdf", PDF_BYTES, "application/pdf")
    project.status = ProjectStatus.ARCHIVED
    project.save(update_fields={"status", "updated_at"})

    list_response = client.get(reverse("documents:list", args=(project.pk,)))
    assert list_response.status_code == 200
    assert "仅可查看和下载" in list_response.content.decode()
    assert client.get(reverse("documents:upload", args=(project.pk,))).status_code == 403
    assert client.get(reverse("documents:category_create", args=(project.pk,))).status_code == 403

    project.deleted_at = timezone.now()
    project.save(update_fields={"deleted_at", "updated_at"})
    assert client.get(reverse("documents:list", args=(project.pk,))).status_code == 404


def test_non_portal_user_is_rejected_before_object_lookup(page_context):
    _, _, project, _ = page_context
    non_portal = make_user("document-non-portal")
    non_portal.groups.remove(Group.objects.get(name=LAB_MEMBER_GROUP))
    client = Client()
    client.force_login(non_portal)

    with patch("apps.documents.views.get_object_or_404") as lookup:
        response = client.get(reverse("documents:list", args=(project.pk,)))

    assert response.status_code == 403
    lookup.assert_not_called()


@pytest.mark.parametrize(
    ("route_name", "method", "args_factory"),
    [
        ("documents:upload", "post", lambda project, document: (project.pk,)),
        ("documents:category_create", "post", lambda project, document: (project.pk,)),
        ("documents:delete", "post", lambda project, document: (project.pk, document.pk)),
        ("documents:restore", "post", lambda project, document: (document.pk,)),
    ],
)
def test_document_write_routes_enforce_csrf(page_context, route_name, method, args_factory):
    owner, pi, project, category = page_context
    _upload(owner, project, category, "csrf.pdf", PDF_BYTES, "application/pdf")
    document = Document.objects.get()
    if route_name == "documents:restore":
        owner.post(reverse("documents:delete", args=(project.pk, document.pk)))
    client = Client(enforce_csrf_checks=True)
    client.force_login(pi)

    response = getattr(client, method)(
        reverse(route_name, args=args_factory(project, document)), {}
    )

    assert response.status_code == 403
