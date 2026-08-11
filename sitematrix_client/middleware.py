"""Gate visitor traffic based on SiteMatrix live/offline status.

If SITEMATRIX_API_KEY is empty, the gate is disabled and the site runs normally.
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse

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

        api_key = (getattr(settings, "SITEMATRIX_API_KEY", "") or "").strip()
        api_base = (getattr(settings, "SITEMATRIX_API_URL", "") or "").rstrip("/")
        fail_open = getattr(settings, "SITEMATRIX_FAIL_OPEN", True)

        # No key configured → SiteMatrix gate is optional / off
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
            if not isinstance(payload, dict):
                raise RuntimeError("SiteMatrix status payload was not a JSON object")
            if payload.get("active"):
                return self.get_response(request)

            offline_url = (payload.get("offline_url") or "").strip()
            if offline_url.startswith("http://") or offline_url.startswith("https://"):
                return redirect(offline_url)
            try:
                return redirect(reverse("sitematrix_client:locked"))
            except NoReverseMatch:
                return self.get_response(request)
        except Exception:
            logger.exception("SiteMatrix status check failed")
            if fail_open:
                return self.get_response(request)
            try:
                return redirect(reverse("sitematrix_client:locked"))
            except NoReverseMatch:
                return self.get_response(request)
