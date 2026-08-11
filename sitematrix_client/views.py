from django.conf import settings
from django.shortcuts import render
from django.views import View


class LockedView(View):
    """Local fallback when SiteMatrix reports the site offline and no offline_url is available."""

    def get(self, request):
        return render(
            request,
            "sitematrix_client/locked.html",
            {
                "site_name": getattr(settings, "SITEMATRIX_SITE_NAME", "") or "This website",
            },
            status=503,
        )
