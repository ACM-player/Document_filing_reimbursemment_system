from datetime import timedelta
from functools import partial
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.constants import LAB_MEMBER_GROUP, SYSTEM_ADMIN_GROUP
from apps.projects.models import (
    AccessRequestStatus,
    ProjectAccessRequest,
    ProjectMembership,
    ProjectRole,
)
from apps.projects.services import (
    expire_access_grants,
    review_access_request,
    submit_access_request,
)

from .project_factories import PASSWORD, make_project, make_project_type, make_user

pytestmark = pytest.mark.django_db


def test_project_pages_require_login():
    response = Client().get(reverse("projects:list"))

    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))


def test_active_member_can_create_project_through_page():
    user = make_user("page-creator")
    project_type = make_project_type()
    client = Client()
    assert client.login(username=user.username, password=PASSWORD)

    response = client.post(
        reverse("projects:create"),
        {
            "project_code": "PAGE-001",
            "name": "页面创建项目",
            "short_name": "页面项目",
            "project_type": project_type.pk,
            "status": "PLANNING",
            "visibility": "INTERNAL",
            "start_date": "",
            "end_date": "",
            "description": "通过普通页面创建",
        },
    )

    assert response.status_code == 302
    project = user.principal_projects.get(project_code="PAGE-001")
    assert response.url == reverse("projects:detail", args=(project.pk,))
    assert ProjectMembership.objects.filter(project=project, user=user, role="PI").exists()


def test_restricted_detail_only_exposes_minimum_until_request_is_approved():
    pi = make_user("page-restricted-pi")
    requester = make_user("page-restricted-requester")
    project = make_project(
        pi=pi,
        visibility="RESTRICTED",
        description="RESTRICTED-SECRET-DESCRIPTION",
    )
    client = Client()
    client.force_login(requester)
    detail_url = reverse("projects:detail", args=(project.pk,))

    response = client.get(detail_url)
    content = response.content.decode()
    assert response.status_code == 200
    assert project.name in content
    assert "RESTRICTED-SECRET-DESCRIPTION" not in content
    assert "申请访问" in content

    response = client.post(
        reverse("projects:access_submit", args=(project.pk,)),
        {"reason": "需要汇总项目档案"},
    )
    assert response.status_code == 302
    access_request = ProjectAccessRequest.objects.get(project=project, requester=requester)
    assert access_request.status == AccessRequestStatus.PENDING

    reviewer = Client()
    reviewer.force_login(pi)
    response = reviewer.post(
        reverse("projects:access_review", args=(project.pk, access_request.pk)),
        {
            "decision": "approve",
            "review_note": "同意",
            "expires_at": (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
        },
    )
    assert response.status_code == 302

    response = client.get(detail_url)
    assert response.status_code == 200
    assert "RESTRICTED-SECRET-DESCRIPTION" in response.content.decode()


def test_internal_reader_cannot_open_edit_or_member_management_pages():
    pi = make_user("page-permission-pi")
    reader = make_user("page-permission-reader")
    project = make_project(pi=pi)
    client = Client()
    client.force_login(reader)

    assert client.get(reverse("projects:detail", args=(project.pk,))).status_code == 200
    assert client.get(reverse("projects:update", args=(project.pk,))).status_code == 403
    assert client.get(reverse("projects:members", args=(project.pk,))).status_code == 403


def test_internal_reader_does_not_see_other_members_or_authorization_metadata():
    pi = make_user("directory-pi")
    reader = make_user("directory-reader")
    other_member = make_user("directory-other")
    project = make_project(pi=pi)
    ProjectMembership.objects.create(
        project=project,
        user=other_member,
        role=ProjectRole.MEMBER,
    )
    client = Client()
    client.force_login(reader)

    response = client.get(reverse("projects:detail", args=(project.pk,)))

    assert response.status_code == 200
    content = response.content.decode()
    assert str(other_member) not in content
    assert "当前项目成员" not in content
    assert "授权来源" not in content


def test_active_non_member_is_rejected_before_project_lookup_for_portal_endpoints():
    pi = make_user("portal-view-pi")
    non_member = make_user("portal-view-user")
    non_member.groups.remove(Group.objects.get(name=LAB_MEMBER_GROUP))
    project = make_project(pi=pi, visibility="RESTRICTED")
    membership = ProjectMembership.objects.get(project=project, user=pi)
    access_request = ProjectAccessRequest.objects.create(
        project=project,
        requester=make_user("portal-view-requester"),
        reason="待处理申请",
    )
    client = Client()
    client.force_login(non_member)

    endpoints = (
        ("get", reverse("projects:list")),
        ("get", reverse("projects:create")),
        ("get", reverse("projects:detail", args=(project.pk,))),
        ("get", reverse("projects:update", args=(project.pk,))),
        ("get", reverse("projects:members", args=(project.pk,))),
        ("post", reverse("projects:member_remove", args=(project.pk, membership.pk))),
        ("post", reverse("projects:access_submit", args=(project.pk,))),
        ("post", reverse("projects:access_review", args=(project.pk, access_request.pk))),
        ("post", reverse("projects:access_cancel", args=(project.pk, access_request.pk))),
        ("post", reverse("projects:delete", args=(project.pk,))),
    )
    for method, url in endpoints:
        response = getattr(client, method)(url)
        assert response.status_code == 403

    unknown = reverse("projects:detail", args=(project.pk,))
    assert client.get(unknown).status_code == 403


def test_system_admin_without_lab_member_has_global_get_and_post_access():
    pi = make_user("system-page-pi")
    system_admin = make_user("system-page-admin")
    system_admin.groups.add(Group.objects.get(name=SYSTEM_ADMIN_GROUP))
    system_admin.groups.remove(Group.objects.get(name=LAB_MEMBER_GROUP))
    target = make_user("system-page-target")
    requester = make_user("system-page-requester")
    project_type = make_project_type(code="SYSTEM-PAGE", name="系统管理员页面")
    project = make_project(
        pi=pi,
        project_type=project_type,
        code="SYSTEM-PAGE-001",
        visibility="RESTRICTED",
    )
    access_request = ProjectAccessRequest.objects.create(
        project=project,
        requester=requester,
        reason="系统管理员审批",
    )
    client = Client()
    client.force_login(system_admin)

    list_response = client.get(reverse("projects:list"))
    assert list_response.status_code == 200
    assert "系统管理员" in list_response.content.decode()
    detail_response = client.get(reverse("projects:detail", args=(project.pk,)))
    assert detail_response.status_code == 200
    assert "系统管理员" in detail_response.content.decode()
    assert client.get(reverse("projects:update", args=(project.pk,))).status_code == 200
    assert client.get(reverse("projects:members", args=(project.pk,))).status_code == 200

    response = client.post(
        reverse("projects:update", args=(project.pk,)),
        {
            "project_code": project.project_code,
            "name": project.name,
            "short_name": "系统管理员更新",
            "project_type": project_type.pk,
            "status": "ACTIVE",
            "visibility": "RESTRICTED",
            "principal_investigator": pi.pk,
            "start_date": "",
            "end_date": "",
            "description": "由系统管理员更新",
        },
    )
    assert response.status_code == 302
    project.refresh_from_db()
    assert project.description == "由系统管理员更新"

    response = client.post(
        reverse("projects:create"),
        {
            "project_code": "SYSTEM-PAGE-CREATE",
            "name": "系统管理员创建",
            "short_name": "",
            "project_type": project_type.pk,
            "status": "PLANNING",
            "visibility": "INTERNAL",
            "start_date": "",
            "end_date": "",
            "description": "",
        },
    )
    assert response.status_code == 302
    created = system_admin.principal_projects.get(project_code="SYSTEM-PAGE-CREATE")

    response = client.post(
        reverse("projects:members", args=(project.pk,)),
        {"user": target.pk, "role": ProjectRole.MEMBER},
    )
    assert response.status_code == 302
    assert ProjectMembership.objects.filter(
        project=project, user=target, left_at__isnull=True
    ).exists()

    response = client.post(
        reverse("projects:access_review", args=(project.pk, access_request.pk)),
        {"decision": "approve", "review_note": "", "expires_at": ""},
    )
    assert response.status_code == 302
    access_request.refresh_from_db()
    assert access_request.status == AccessRequestStatus.APPROVED

    response = client.post(reverse("projects:delete", args=(created.pk,)))
    assert response.status_code == 302
    assert response.url == reverse("projects:list")


def test_access_review_invalid_form_rerenders_bound_form_without_redirect():
    pi = make_user("review-invalid-pi")
    requester = make_user("review-invalid-requester")
    project = make_project(pi=pi, visibility="RESTRICTED")
    access_request = ProjectAccessRequest.objects.create(
        project=project,
        requester=requester,
        reason="需要审核",
    )
    client = Client()
    client.force_login(pi)

    response = client.post(
        reverse("projects:access_review", args=(project.pk, access_request.pk)),
        {"decision": "reject", "review_note": "", "expires_at": "2026-08-20T12:00"},
    )

    assert response.status_code == 200
    form = response.context["managed_requests"][0][1]
    assert form.data["decision"] == "reject"
    assert form.data["expires_at"] == "2026-08-20T12:00"
    assert "拒绝申请时必须填写原因。" in form.errors["review_note"]


def test_access_review_service_error_rerenders_bound_form_without_redirect():
    pi = make_user("review-service-pi")
    requester = make_user("review-service-requester")
    project = make_project(pi=pi, visibility="RESTRICTED")
    access_request = ProjectAccessRequest.objects.create(
        project=project,
        requester=requester,
        reason="需要审核",
    )
    client = Client()
    client.force_login(pi)
    url = reverse("projects:access_review", args=(project.pk, access_request.pk))

    with patch(
        "apps.projects.views.review_access_request",
        side_effect=ValidationError("服务拒绝该审核"),
    ):
        response = client.post(
            url,
            {"decision": "approve", "review_note": "保留说明", "expires_at": ""},
        )

    assert response.status_code == 200
    form = response.context["managed_requests"][0][1]
    assert form.data["decision"] == "approve"
    assert form.data["review_note"] == "保留说明"
    assert "服务拒绝该审核" in form.non_field_errors()


def test_unprivileged_reviewer_is_rejected_even_when_review_form_is_invalid():
    pi = make_user("review-denied-pi")
    reader = make_user("review-denied-reader")
    requester = make_user("review-denied-requester")
    project = make_project(pi=pi, visibility="RESTRICTED")
    access_request = ProjectAccessRequest.objects.create(
        project=project,
        requester=requester,
        reason="需要审核",
    )
    client = Client()
    client.force_login(reader)

    response = client.post(
        reverse("projects:access_review", args=(project.pk, access_request.pk)),
        {"decision": "reject", "review_note": ""},
    )

    assert response.status_code == 403


def test_member_remove_cross_project_idor_is_not_found_and_self_removal_goes_to_detail():
    pi = make_user("remove-pi")
    manager = make_user("remove-manager")
    other_pi = make_user("remove-other-pi")
    project = make_project(pi=pi)
    other_project = make_project(
        pi=other_pi,
        project_type=project.project_type,
        code="REMOVE-OTHER",
    )
    self_membership = ProjectMembership.objects.create(
        project=project,
        user=manager,
        role=ProjectRole.MANAGER,
    )
    other_membership = ProjectMembership.objects.get(project=other_project, user=other_pi)
    client = Client()
    client.force_login(manager)

    response = client.post(
        reverse("projects:member_remove", args=(project.pk, other_membership.pk))
    )
    assert response.status_code == 404

    response = client.post(reverse("projects:member_remove", args=(project.pk, self_membership.pk)))
    assert response.status_code == 302
    assert response.url == reverse("projects:detail", args=(project.pk,))


def test_cross_project_access_request_idor_and_soft_deleted_project_endpoints_are_not_found():
    pi = make_user("idor-pi")
    requester = make_user("idor-requester")
    other_pi = make_user("idor-other-pi")
    project = make_project(pi=pi, visibility="RESTRICTED")
    other_project = make_project(
        pi=other_pi,
        project_type=project.project_type,
        code="IDOR-OTHER",
        visibility="RESTRICTED",
    )
    other_request = ProjectAccessRequest.objects.create(
        project=other_project,
        requester=requester,
        reason="另一项目申请",
    )
    client = Client()
    client.force_login(pi)

    assert (
        client.post(
            reverse("projects:access_review", args=(project.pk, other_request.pk))
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse("projects:access_cancel", args=(project.pk, other_request.pk))
        ).status_code
        == 404
    )
    project.deleted_at = timezone.now()
    project.save(update_fields={"deleted_at", "updated_at"})
    assert client.get(reverse("projects:detail", args=(project.pk,))).status_code == 404
    assert client.get(reverse("projects:members", args=(project.pk,))).status_code == 404
    assert client.post(reverse("projects:delete", args=(project.pk,))).status_code == 404


@pytest.mark.parametrize(
    ("route_name", "kwargs", "data"),
    [
        ("projects:create", (), {}),
        ("projects:update", ("project",), {}),
        ("projects:members", ("project",), {}),
        ("projects:member_remove", ("project", "membership"), {}),
        ("projects:access_submit", ("project",), {}),
        ("projects:access_review", ("project", "request"), {}),
        ("projects:access_cancel", ("project", "request"), {}),
        ("projects:delete", ("project",), {}),
    ],
)
def test_project_writes_require_csrf_token(route_name, kwargs, data):
    pi = make_user(f"csrf-pi-{route_name.rsplit(':', 1)[1]}")
    requester = make_user(f"csrf-requester-{route_name.rsplit(':', 1)[1]}")
    project = make_project(
        pi=pi, code=f"CSRF-{route_name.rsplit(':', 1)[1]}", visibility="RESTRICTED"
    )
    membership = ProjectMembership.objects.get(project=project, user=pi)
    access_request = ProjectAccessRequest.objects.create(
        project=project,
        requester=requester,
        reason="CSRF",
    )
    client = Client(enforce_csrf_checks=True)
    client.force_login(pi)
    values = {"project": project.pk, "membership": membership.pk, "request": access_request.pk}

    response = client.post(reverse(route_name, args=[values[name] for name in kwargs]), data)

    assert response.status_code == 403


def test_project_write_with_csrf_token_executes_normally():
    user = make_user("csrf-success-user")
    project_type = make_project_type(code="CSRF-SUCCESS", name="CSRF 成功")
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    response = client.get(reverse("projects:create"))
    token = response.cookies["csrftoken"].value

    response = client.post(
        reverse("projects:create"),
        {
            "csrfmiddlewaretoken": token,
            "project_code": "CSRF-SUCCESS-001",
            "name": "CSRF 正常提交",
            "short_name": "",
            "project_type": project_type.pk,
            "status": "PLANNING",
            "visibility": "INTERNAL",
            "start_date": "",
            "end_date": "",
            "description": "",
        },
        HTTP_REFERER="http://testserver/projects/create/",
    )

    assert response.status_code == 302


@pytest.mark.parametrize("route_name", ["projects:detail", "projects:members"])
def test_project_management_pages_normalize_all_elapsed_grants(route_name):
    pi = make_user(f"expiry-page-pi-{route_name.rsplit(':', 1)[1]}")
    requester = make_user(f"expiry-page-requester-{route_name.rsplit(':', 1)[1]}")
    project = make_project(pi=pi, visibility="RESTRICTED")
    expires_at = timezone.now() + timedelta(days=1)
    access_request = submit_access_request(
        actor=requester,
        project=project,
        reason="验证管理页面归一化到期授权",
    )
    access_request = review_access_request(
        actor=pi,
        access_request=access_request,
        approve=True,
        expires_at=expires_at,
    )
    membership = access_request.granted_membership
    client = Client()
    client.force_login(pi)

    expired_at = expires_at + timedelta(seconds=1)
    with patch(
        "apps.projects.views.expire_access_grants",
        new=partial(expire_access_grants, at=expired_at),
    ):
        response = client.get(reverse(route_name, args=(project.pk,)))

    assert response.status_code == 200
    access_request.refresh_from_db()
    membership.refresh_from_db()
    assert access_request.status == AccessRequestStatus.EXPIRED
    assert membership.left_at == expired_at
