import uuid

from django.shortcuts import redirect
from django.urls import Resolver404, resolve


class RequestIDMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = uuid.uuid4()
        response = self.get_response(request)
        response["X-Request-ID"] = str(request.request_id)
        return response


class ForcePasswordChangeMiddleware:
    allowed_view_names = {
        "accounts:login",
        "accounts:logout",
        "accounts:password_change",
        "health",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if getattr(user, "is_authenticated", False) and user.must_change_password:
            try:
                view_name = resolve(request.path_info).view_name
            except Resolver404:
                view_name = ""
            if view_name not in self.allowed_view_names:
                return redirect("accounts:password_change")
        return self.get_response(request)
