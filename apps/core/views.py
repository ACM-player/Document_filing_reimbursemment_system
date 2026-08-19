from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.shortcuts import render


@login_required
def home(request: HttpRequest):
    return render(request, "core/home.html")


def health(request: HttpRequest) -> JsonResponse:
    return JsonResponse(
        {
            "service": "labarchive",
            "status": "ok",
            "environment": settings.LABARCHIVE_ENV,
        }
    )
