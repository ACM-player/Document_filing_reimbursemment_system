import threading
import traceback
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection, connections, transaction
from django.utils import timezone

from apps.accounts.constants import SYSTEM_ADMIN_GROUP
from apps.accounts.models import AccountStatus, User
from apps.accounts.services import change_user_status
from apps.audit.models import AuditAction, AuditLog
from apps.projects import services as project_services
from apps.projects.models import (
    AccessRequestStatus,
    Project,
    ProjectAccessRequest,
    ProjectMembership,
    ProjectRole,
    ProjectVisibility,
)
from apps.projects.services import (
    cancel_or_revoke_access_request,
    expire_access_grants,
    remove_project_member,
    review_access_request,
    set_project_member,
    submit_access_request,
    update_project,
)

from .project_factories import make_project, make_user

pytestmark = pytest.mark.django_db(transaction=True)

THREAD_TIMEOUT_SECONDS = 10
EVENT_TIMEOUT_SECONDS = 5


def _make_system_admin(username):
    user = make_user(username)
    user.groups.add(Group.objects.get(name=SYSTEM_ADMIN_GROUP))
    return user


def _set_local_timeouts():
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout = '5s'")
        cursor.execute("SET LOCAL statement_timeout = '10s'")


def _wait(event, description):
    assert event.wait(EVENT_TIMEOUT_SECONDS), f"Timed out waiting for {description}."


def _run_workers(workers):
    errors = {}
    lock = threading.Lock()

    def make_target(name, work):
        def target():
            close_old_connections()
            try:
                with transaction.atomic():
                    _set_local_timeouts()
                    work()
            except BaseException:
                with lock:
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


def _lock_users_in_order(*user_ids):
    return list(User.objects.select_for_update().filter(pk__in=user_ids).order_by("pk"))


def test_departure_blocks_direct_assignment_then_leaves_no_active_membership():
    admin = _make_system_admin("concurrency-departure-direct-admin")
    pi = make_user("concurrency-departure-direct-pi")
    target = make_user("concurrency-departure-direct-target")
    project = make_project(
        pi=pi,
        code="CONCURRENCY-DEPARTURE-DIRECT",
        visibility=ProjectVisibility.RESTRICTED,
    )
    target_locked = threading.Event()
    assignment_ready = threading.Event()
    assignment_outcome = {}

    def depart():
        User.objects.select_for_update().get(pk=target.pk)
        target_locked.set()
        _wait(assignment_ready, "direct assignment to be ready")
        change_user_status(
            user=User.objects.get(pk=target.pk),
            new_status=AccountStatus.DEPARTED,
            actor=User.objects.get(pk=admin.pk),
        )

    def assign_directly():
        _wait(target_locked, "departure to lock the target user")
        assignment_ready.set()
        try:
            set_project_member(
                actor=User.objects.get(pk=pi.pk),
                project=Project.objects.get(pk=project.pk),
                user=User.objects.get(pk=target.pk),
                role=ProjectRole.MEMBER,
            )
        except (PermissionDenied, ValidationError):
            assignment_outcome["rejected"] = True

    _run_workers({"departure": depart, "direct-assignment": assign_directly})

    target.refresh_from_db()
    assert assignment_outcome == {"rejected": True}
    assert target.account_status == AccountStatus.DEPARTED
    assert not ProjectMembership.objects.filter(
        project=project,
        user=target,
        left_at__isnull=True,
    ).exists()


def test_departure_blocks_approval_then_cancels_pending_request_without_grant():
    admin = _make_system_admin("concurrency-departure-approval-admin")
    pi = make_user("concurrency-departure-approval-pi")
    target = make_user("concurrency-departure-approval-target")
    project = make_project(
        pi=pi,
        code="CONCURRENCY-DEPARTURE-APPROVAL",
        visibility=ProjectVisibility.RESTRICTED,
    )
    access_request = submit_access_request(actor=target, project=project, reason="并发审批")
    target_locked = threading.Event()
    approval_ready = threading.Event()
    approval_outcome = {}

    def depart():
        User.objects.select_for_update().get(pk=target.pk)
        target_locked.set()
        _wait(approval_ready, "approval to be ready")
        change_user_status(
            user=User.objects.get(pk=target.pk),
            new_status=AccountStatus.DEPARTED,
            actor=User.objects.get(pk=admin.pk),
        )

    def approve():
        _wait(target_locked, "departure to lock the target user")
        approval_ready.set()
        try:
            review_access_request(
                actor=User.objects.get(pk=pi.pk),
                access_request=ProjectAccessRequest.objects.get(pk=access_request.pk),
                approve=True,
            )
        except ValidationError:
            approval_outcome["rejected"] = True

    _run_workers({"departure": depart, "approval": approve})

    access_request.refresh_from_db()
    target.refresh_from_db()
    assert approval_outcome == {"rejected": True}
    assert target.account_status == AccountStatus.DEPARTED
    assert access_request.status == AccessRequestStatus.CANCELLED
    assert not ProjectMembership.objects.filter(source_access_request=access_request).exists()
    assert (
        AuditLog.objects.filter(
            action=AuditAction.ACCESS_REQUEST_APPROVED,
            object_id=str(access_request.pk),
        ).count()
        == 0
    )


def test_pi_transfer_precedes_old_pi_departure_without_deadlock():
    admin = _make_system_admin("concurrency-transfer-admin")
    old_pi = make_user("concurrency-transfer-old-pi")
    new_pi = make_user("concurrency-transfer-new-pi")
    project = make_project(
        pi=old_pi,
        code="CONCURRENCY-TRANSFER-DEPARTURE",
        visibility=ProjectVisibility.RESTRICTED,
    )
    users_locked = threading.Event()
    release_transfer = threading.Event()
    departure_ready = threading.Event()
    original_lock_user_ids = project_services._lock_user_ids

    def transfer_lock_user_ids(*user_ids):
        locked_users = original_lock_user_ids(*user_ids)
        if threading.current_thread().name == "pi-transfer":
            users_locked.set()
            _wait(release_transfer, "PI transfer release")
        return locked_users

    def transfer():
        update_project(
            actor=User.objects.get(pk=admin.pk),
            project=Project.objects.get(pk=project.pk),
            cleaned_data={"principal_investigator": User.objects.get(pk=new_pi.pk)},
        )

    def depart_old_pi():
        _wait(users_locked, "PI transfer to lock users")
        departure_ready.set()
        change_user_status(
            user=User.objects.get(pk=old_pi.pk),
            new_status=AccountStatus.DEPARTED,
            actor=User.objects.get(pk=admin.pk),
        )

    with patch.object(project_services, "_lock_user_ids", side_effect=transfer_lock_user_ids):
        errors = {}
        errors_lock = threading.Lock()

        def run_transfer():
            close_old_connections()
            try:
                with transaction.atomic():
                    _set_local_timeouts()
                    transfer()
            except BaseException:
                with errors_lock:
                    errors["pi-transfer"] = traceback.format_exc()
            finally:
                connections.close_all()

        def run_departure():
            close_old_connections()
            try:
                with transaction.atomic():
                    _set_local_timeouts()
                    depart_old_pi()
            except BaseException:
                with errors_lock:
                    errors["old-pi-departure"] = traceback.format_exc()
            finally:
                connections.close_all()

        transfer_worker = threading.Thread(name="pi-transfer", target=run_transfer, daemon=True)
        departure_worker = threading.Thread(
            name="old-pi-departure", target=run_departure, daemon=True
        )
        transfer_worker.start()
        _wait(users_locked, "PI transfer to lock users")
        departure_worker.start()
        _wait(departure_ready, "old PI departure to start")
        release_transfer.set()
        for worker in (transfer_worker, departure_worker):
            worker.join(THREAD_TIMEOUT_SECONDS)
        alive = [worker.name for worker in (transfer_worker, departure_worker) if worker.is_alive()]
        assert not alive, f"Worker threads did not finish before timeout: {alive}"
        assert not errors, "Worker exceptions:\n" + "\n".join(
            f"[{name}]\n{error}" for name, error in errors.items()
        )

    project.refresh_from_db()
    old_pi.refresh_from_db()
    old_membership = ProjectMembership.objects.get(project=project, user=old_pi)
    new_membership = ProjectMembership.objects.get(project=project, user=new_pi)
    assert project.principal_investigator_id == new_pi.pk
    assert old_pi.account_status == AccountStatus.DEPARTED
    assert old_membership.left_at is not None
    assert new_membership.role == ProjectRole.PI
    assert new_membership.left_at is None


def test_request_backed_removal_and_revoke_write_one_revocation_audit():
    pi = make_user("concurrency-removal-revoke-pi")
    requester = make_user("concurrency-removal-revoke-requester")
    project = make_project(
        pi=pi,
        code="CONCURRENCY-REMOVAL-REVOKE",
        visibility=ProjectVisibility.RESTRICTED,
    )
    access_request = review_access_request(
        actor=pi,
        access_request=submit_access_request(actor=requester, project=project, reason="并发撤销"),
        approve=True,
    )
    membership = access_request.granted_membership
    start = threading.Barrier(2, timeout=EVENT_TIMEOUT_SECONDS)

    def remove():
        start.wait()
        remove_project_member(
            actor=User.objects.get(pk=pi.pk),
            membership=ProjectMembership.objects.get(pk=membership.pk),
        )

    def revoke():
        start.wait()
        cancel_or_revoke_access_request(
            actor=User.objects.get(pk=pi.pk),
            access_request=ProjectAccessRequest.objects.get(pk=access_request.pk),
        )

    _run_workers({"request-backed-removal": remove, "revoke": revoke})

    access_request.refresh_from_db()
    membership.refresh_from_db()
    assert access_request.status == AccessRequestStatus.CANCELLED
    assert membership.left_at is not None
    assert (
        AuditLog.objects.filter(
            action=AuditAction.ACCESS_REQUEST_REVOKED,
            object_id=str(access_request.pk),
        ).count()
        == 1
    )


def test_removal_precedes_expiry_and_leaves_one_terminal_audit_without_deadlock():
    pi = make_user("concurrency-removal-expiry-pi")
    requester = make_user("concurrency-removal-expiry-requester")
    project = make_project(
        pi=pi,
        code="CONCURRENCY-REMOVAL-EXPIRY",
        visibility=ProjectVisibility.RESTRICTED,
    )
    expires_at = timezone.now() + timedelta(minutes=1)
    access_request = review_access_request(
        actor=pi,
        access_request=submit_access_request(actor=requester, project=project, reason="并发到期"),
        approve=True,
        expires_at=expires_at,
    )
    membership = access_request.granted_membership
    removal_has_locks = threading.Event()
    expiry_about_to_lock_user = threading.Event()
    original_lock_user_ids = project_services._lock_user_ids

    def expiry_lock_user_ids(*user_ids):
        if threading.current_thread().name == "expiry":
            expiry_about_to_lock_user.set()
        return original_lock_user_ids(*user_ids)

    def remove():
        _lock_users_in_order(pi.pk, requester.pk)
        Project.objects.select_for_update().get(pk=project.pk)
        ProjectAccessRequest.objects.select_for_update().get(pk=access_request.pk)
        removal_has_locks.set()
        _wait(expiry_about_to_lock_user, "expiry worker to reach its user lock")
        remove_project_member(
            actor=User.objects.get(pk=pi.pk),
            membership=ProjectMembership.objects.get(pk=membership.pk),
        )

    def expire():
        _wait(removal_has_locks, "removal worker to lock the access state")
        expire_access_grants(
            project=Project.objects.get(pk=project.pk),
            at=expires_at + timedelta(seconds=1),
        )

    with patch.object(project_services, "_lock_user_ids", side_effect=expiry_lock_user_ids):
        _run_workers({"removal": remove, "expiry": expire})

    access_request.refresh_from_db()
    membership.refresh_from_db()
    assert access_request.status == AccessRequestStatus.CANCELLED
    assert membership.left_at is not None
    assert (
        AuditLog.objects.filter(
            object_id=str(access_request.pk),
            action__in=(AuditAction.ACCESS_REQUEST_REVOKED, AuditAction.ACCESS_REQUEST_EXPIRED),
        ).count()
        == 1
    )
    assert (
        AuditLog.objects.filter(
            action=AuditAction.ACCESS_REQUEST_REVOKED,
            object_id=str(access_request.pk),
        ).count()
        == 1
    )
