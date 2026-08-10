from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.shortcuts import render


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
