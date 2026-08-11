"""Gate visitor traffic based on SiteMatrix live/offline status."""

from __future__ import annotations

import logging

import requests
from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse

logger = logging.getLogger(__name__)

SKIP_PREFIXES = (
    "/static/",
    "/media/",
    "/locked",
    "/admin/",
    "/health",
    "/favicon.ico",
)


class SiteMatrixGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or "/"
        if any(path.startswith(prefix) for prefix in SKIP_PREFIXES):
            return self.get_response(request)

        api_key = getattr(settings, "SITEMATRIX_API_KEY", "") or ""
        api_base = (getattr(settings, "SITEMATRIX_API_URL", "") or "").rstrip("/")
        fail_open = getattr(settings, "SITEMATRIX_FAIL_OPEN", True)

        if not api_key or not api_base:
            return self.get_response(request)

        try:
            response = requests.get(
                f"{api_base}/api/v1/status/",
                headers={"X-Site-API-Key": api_key},
                timeout=getattr(settings, "SITEMATRIX_TIMEOUT", 3),
            )
            if response.status_code != 200:
                raise RuntimeError(f"SiteMatrix status HTTP {response.status_code}")
            payload = response.json()
            if payload.get("active"):
                return self.get_response(request)

            offline_url = (payload.get("offline_url") or "").strip()
            if offline_url:
                return redirect(offline_url)
            return redirect(reverse("sitematrix_client:locked"))
        except Exception:
            logger.exception("SiteMatrix status check failed")
            if fail_open:
                return self.get_response(request)
            return redirect(reverse("sitematrix_client:locked"))
