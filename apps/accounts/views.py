from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from apps.audit.models import AuditAction, AuditResult
from apps.audit.services import record_audit_event

from .forms import GENERIC_LOGIN_ERROR, LoginForm, SelfProfileDetailsForm, SelfProfileForm
from .throttling import (
    clear_login_failures,
    is_login_locked,
    register_login_failure,
    username_fingerprint,
)


def _source_ip(request):
    return request.META.get("REMOTE_ADDR")


def _safe_login_destination(request) -> str:
    candidate = request.POST.get("next") or request.GET.get("next")
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return reverse("home")


@never_cache
@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("home")

    form = LoginForm(request=request, data=request.POST or None)
    if request.method == "POST":
        username = request.POST.get("username", "")
        source_ip = _source_ip(request)
        fingerprint = username_fingerprint(username) if username else ""

        if username and is_login_locked(username, source_ip):
            form.add_error(None, GENERIC_LOGIN_ERROR)
            record_audit_event(
                action=AuditAction.LOGIN_FAILED,
                request=request,
                description="登录请求处于限制期",
                new_value={"username_fingerprint": fingerprint},
                result=AuditResult.DENIED,
            )
        elif form.is_valid():
            user = form.get_user()
            clear_login_failures(username, source_ip)
            auth_login(request, user)
            record_audit_event(
                action=AuditAction.LOGIN_SUCCESS,
                request=request,
                actor=user,
                subject=user,
                description="用户登录成功",
            )
            if user.must_change_password:
                return redirect("accounts:password_change")
            return redirect(_safe_login_destination(request))
        else:
            if username:
                register_login_failure(username, source_ip)
            record_audit_event(
                action=AuditAction.LOGIN_FAILED,
                request=request,
                description="用户名、密码或账号状态未通过认证",
                new_value={"username_fingerprint": fingerprint},
                result=AuditResult.DENIED,
            )

    return render(request, "accounts/login.html", {"form": form})


@login_required
@require_POST
def logout_view(request):
    actor = request.user
    record_audit_event(
        action=AuditAction.LOGOUT,
        request=request,
        actor=actor,
        subject=actor,
        description="用户退出登录",
    )
    auth_logout(request)
    return redirect("accounts:login")


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def password_change_view(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save(commit=False)
            user.must_change_password = False
            user.save(update_fields={"password", "must_change_password", "updated_at"})
            record_audit_event(
                action=AuditAction.PASSWORD_CHANGED,
                request=request,
                actor=user,
                subject=user,
                description="用户修改密码",
                new_value={"must_change_password": False},
            )
        update_session_auth_hash(request, user)
        messages.success(request, "密码已更新。")
        return redirect("home")
    return render(request, "accounts/password_change.html", {"form": form})


@login_required
@require_http_methods(["GET", "POST"])
def profile_view(request):
    profile = request.user.profile
    user_form = SelfProfileForm(request.POST or None, instance=request.user, prefix="user")
    profile_form = SelfProfileDetailsForm(
        request.POST or None,
        instance=profile,
        prefix="profile",
    )
    if request.method == "POST" and user_form.is_valid() and profile_form.is_valid():
        changed_fields = sorted({*user_form.changed_data, *profile_form.changed_data})
        with transaction.atomic():
            user_form.save()
            profile_form.save()
            record_audit_event(
                action=AuditAction.PROFILE_UPDATED,
                request=request,
                actor=request.user,
                subject=request.user,
                description="用户更新个人资料",
                new_value={"changed_fields": changed_fields},
            )
        messages.success(request, "个人资料已更新。")
        return redirect("accounts:profile")
    return render(
        request,
        "accounts/profile.html",
        {"user_form": user_form, "profile_form": profile_form},
    )
