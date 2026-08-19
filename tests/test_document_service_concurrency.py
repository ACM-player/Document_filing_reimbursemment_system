import threading
import traceback
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connection, connections

from apps.accounts.constants import SYSTEM_ADMIN_GROUP
from apps.accounts.models import AccountStatus, User
from apps.accounts.services import change_user_status
from apps.audit.models import AuditAction, AuditLog, AuditResult
from apps.documents import services as document_services
from apps.documents.models import Document, DocumentCategory, FileAsset, FileStorageStatus
from apps.documents.reconciliation import reconcile_document_storage
from apps.documents.scanning import ScanResult
from apps.documents.services import (
    DocumentUploadError,
    restore_document,
    soft_delete_document,
    upload_document,
)
from apps.documents.storage import ControlledFileStorage
from apps.projects.models import Project, ProjectStatus
from apps.projects.services import update_project

from .project_factories import make_project, make_user

pytestmark = pytest.mark.django_db(transaction=True)

THREAD_TIMEOUT_SECONDS = 10
EVENT_TIMEOUT_SECONDS = 5
PDF_BYTES = b"%PDF-1.7\nconcurrency-evidence\n%%EOF\n"


def _wait(event, description):
    assert event.wait(EVENT_TIMEOUT_SECONDS), f"Timed out waiting for {description}."


def _run_workers(workers):
    errors = {}
    errors_lock = threading.Lock()

    def make_target(name, work):
        def target():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute("SET statement_timeout = '10s'")
                work()
            except BaseException:
                with errors_lock:
                    errors[name] = traceback.format_exc()
            finally:
                connections.close_all()

        return target

    threads = [
        threading.Thread(name=name, target=make_target(name, work), daemon=True)
        for name, work in workers.items()
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(THREAD_TIMEOUT_SECONDS)
    alive = [thread.name for thread in threads if thread.is_alive()]
    assert not alive, f"Worker threads did not finish before timeout: {alive}"
    assert not errors, "Worker exceptions:\n" + "\n".join(
        f"[{name}]\n{error}" for name, error in errors.items()
    )


def _system_admin(username):
    user = make_user(username)
    user.groups.add(Group.objects.get(name=SYSTEM_ADMIN_GROUP))
    return user


def _storage(tmp_path, settings):
    media_root = tmp_path / "media"
    settings.MEDIA_ROOT = media_root
    settings.LABARCHIVE_STAGING_ROOT = media_root / ".staging"
    return ControlledFileStorage()


def _upload(*, actor, project, category, storage, token=None):
    return upload_document(
        actor=actor,
        project=project,
        category=category,
        uploaded_file=SimpleUploadedFile(
            "并发.pdf",
            PDF_BYTES,
            content_type="application/pdf",
        ),
        upload_token=token or uuid4(),
        title="并发证据",
        storage=storage,
    )


def test_concurrent_upload_same_token_has_one_global_owner(tmp_path, settings):
    first_actor = make_user("token-race-first")
    second_actor = make_user("token-race-second")
    first_project = make_project(pi=first_actor, code="TOKEN-RACE-FIRST")
    second_project = make_project(
        pi=second_actor,
        code="TOKEN-RACE-SECOND",
        project_type=first_project.project_type,
    )
    category = DocumentCategory.objects.create(code="TOKEN-RACE", name="令牌竞态")
    storage = _storage(tmp_path, settings)
    token = uuid4()
    start = threading.Barrier(2, timeout=EVENT_TIMEOUT_SECONDS)
    outcomes = {}

    def attempt(name, actor_id, project_id):
        start.wait()
        try:
            outcome = _upload(
                actor=User.objects.get(pk=actor_id),
                project=Project.objects.get(pk=project_id),
                category=DocumentCategory.objects.get(pk=category.pk),
                storage=storage,
                token=token,
            )
        except PermissionDenied:
            outcomes[name] = "denied"
        else:
            outcomes[name] = str(outcome.document.pk)

    _run_workers(
        {
            "first": lambda: attempt("first", first_actor.pk, first_project.pk),
            "second": lambda: attempt("second", second_actor.pk, second_project.pk),
        }
    )

    assert list(outcomes.values()).count("denied") == 1
    assert FileAsset.objects.filter(upload_token=token).count() == 1
    assert AuditLog.objects.filter(action=AuditAction.FILE_UPLOADED).count() == 1


@pytest.mark.parametrize("state_change", ["archive", "disable"])
def test_upload_rechecks_project_and_account_after_publish(
    tmp_path,
    settings,
    state_change,
):
    actor = make_user(f"upload-race-{state_change}-actor")
    admin = _system_admin(f"upload-race-{state_change}-admin")
    project = make_project(pi=actor, code=f"UPLOAD-RACE-{state_change.upper()}")
    category = DocumentCategory.objects.create(code=f"UP-{state_change}", name=state_change)
    promoted = threading.Event()
    release_upload = threading.Event()

    class PausingStorage(ControlledFileStorage):
        def promote(self, staged_path, relative_key):
            destination = super().promote(staged_path, relative_key)
            promoted.set()
            _wait(release_upload, "state change to commit")
            return destination

    media_root = tmp_path / "media"
    settings.MEDIA_ROOT = media_root
    settings.LABARCHIVE_STAGING_ROOT = media_root / ".staging"
    storage = PausingStorage()
    upload_result = {}

    def upload():
        try:
            _upload(
                actor=User.objects.get(pk=actor.pk),
                project=Project.objects.get(pk=project.pk),
                category=DocumentCategory.objects.get(pk=category.pk),
                storage=storage,
            )
        except DocumentUploadError as exc:
            upload_result["code"] = exc.code

    def change_state():
        _wait(promoted, "upload to publish physical bytes")
        if state_change == "archive":
            update_project(
                actor=User.objects.get(pk=admin.pk),
                project=Project.objects.get(pk=project.pk),
                cleaned_data={"status": ProjectStatus.ARCHIVED},
            )
        else:
            change_user_status(
                user=User.objects.get(pk=actor.pk),
                new_status=AccountStatus.DISABLED,
                actor=User.objects.get(pk=admin.pk),
            )
        release_upload.set()

    _run_workers({"upload": upload, "state-change": change_state})

    asset = FileAsset.objects.get()
    assert upload_result == {"code": "finalization_failed"}
    assert asset.storage_status == FileStorageStatus.QUARANTINED
    assert asset.status_reason == "authorization_changed_after_publish"
    assert AuditLog.objects.filter(action=AuditAction.FILE_UPLOADED).count() == 0
    assert AuditLog.objects.filter(action=AuditAction.FILE_QUARANTINED).count() == 1


@pytest.mark.parametrize("state_change", ["archive", "disable"])
def test_restore_rechecks_project_and_account_after_validation(
    tmp_path,
    settings,
    state_change,
):
    actor = make_user(f"restore-race-{state_change}-actor")
    admin = _system_admin(f"restore-race-{state_change}-admin")
    project = make_project(pi=actor, code=f"RESTORE-RACE-{state_change.upper()}")
    category = DocumentCategory.objects.create(code=f"RS-{state_change}", name=state_change)
    storage = _storage(tmp_path, settings)
    document = _upload(
        actor=actor,
        project=project,
        category=category,
        storage=storage,
    ).document
    soft_delete_document(actor=actor, document=document)
    scan_started = threading.Event()
    release_restore = threading.Event()
    restore_result = {}

    class PausingScanner:
        def scan(self, path):
            assert path.read_bytes() == PDF_BYTES
            scan_started.set()
            _wait(release_restore, "state change to commit")
            return ScanResult("NOT_CONFIGURED", "scanner_not_configured")

    def restore():
        try:
            restore_document(
                actor=User.objects.get(pk=actor.pk),
                document=Document.all_objects.get(pk=document.pk),
                storage=storage,
                scanner=PausingScanner(),
            )
        except PermissionDenied:
            restore_result["denied"] = True

    def change_state():
        _wait(scan_started, "restore validation to reach scanner")
        if state_change == "archive":
            update_project(
                actor=User.objects.get(pk=admin.pk),
                project=Project.objects.get(pk=project.pk),
                cleaned_data={"status": ProjectStatus.ARCHIVED},
            )
        else:
            change_user_status(
                user=User.objects.get(pk=actor.pk),
                new_status=AccountStatus.DISABLED,
                actor=User.objects.get(pk=admin.pk),
            )
        release_restore.set()

    _run_workers({"restore": restore, "state-change": change_state})

    current = Document.all_objects.select_related("file_asset").get(pk=document.pk)
    assert restore_result == {"denied": True}
    assert current.deleted_at is not None
    assert current.file_asset.storage_status == FileStorageStatus.DELETED
    assert not AuditLog.objects.filter(
        action=AuditAction.DOCUMENT_RESTORED,
        result=AuditResult.SUCCESS,
    ).exists()


def test_delete_and_archive_follow_one_lock_order_without_half_state(tmp_path, settings):
    actor = make_user("delete-archive-actor")
    admin = _system_admin("delete-archive-admin")
    project = make_project(pi=actor, code="DELETE-ARCHIVE")
    category = DocumentCategory.objects.create(code="DELETE-ARCHIVE", name="删除归档")
    storage = _storage(tmp_path, settings)
    document = _upload(
        actor=actor,
        project=project,
        category=category,
        storage=storage,
    ).document
    project_locked = threading.Event()
    archive_ready = threading.Event()
    original_lock_projects = document_services._lock_projects

    def pausing_lock_projects(project_ids):
        locked = original_lock_projects(project_ids)
        if threading.current_thread().name == "delete":
            project_locked.set()
            _wait(archive_ready, "archive worker to wait for project lock")
        return locked

    def delete():
        soft_delete_document(
            actor=User.objects.get(pk=actor.pk),
            document=Document.all_objects.get(pk=document.pk),
        )

    def archive():
        _wait(project_locked, "delete worker to lock project")
        archive_ready.set()
        update_project(
            actor=User.objects.get(pk=admin.pk),
            project=Project.objects.get(pk=project.pk),
            cleaned_data={"status": ProjectStatus.ARCHIVED},
        )

    with patch.object(document_services, "_lock_projects", side_effect=pausing_lock_projects):
        _run_workers({"delete": delete, "archive": archive})

    current = Document.all_objects.select_related("file_asset", "project").get(pk=document.pk)
    assert current.deleted_at is not None
    assert current.file_asset.storage_status == FileStorageStatus.DELETED
    assert current.project.status == ProjectStatus.ARCHIVED
    assert AuditLog.objects.filter(action=AuditAction.DOCUMENT_SOFT_DELETED).count() == 1
    assert AuditLog.objects.filter(action=AuditAction.PROJECT_ARCHIVED).count() == 1


def test_concurrent_reconciliation_marks_missing_once(tmp_path, settings):
    actor = make_user("reconcile-race-actor")
    project = make_project(pi=actor, code="RECONCILE-RACE")
    category = DocumentCategory.objects.create(code="RECONCILE-RACE", name="核对竞态")
    storage = _storage(tmp_path, settings)
    document = _upload(
        actor=actor,
        project=project,
        category=category,
        storage=storage,
    ).document
    storage.resolve_final(document.file_asset.relative_path).unlink()
    start = threading.Barrier(2, timeout=EVENT_TIMEOUT_SECONDS)

    def reconcile():
        start.wait()
        reconcile_document_storage(storage=storage)

    _run_workers({"first-reconcile": reconcile, "second-reconcile": reconcile})

    asset = FileAsset.objects.get(pk=document.file_asset_id)
    assert asset.storage_status == FileStorageStatus.MISSING
    assert AuditLog.objects.filter(action=AuditAction.FILE_MARKED_MISSING).count() == 1
