"""Append-only audit logging for planner actions."""

from __future__ import annotations

from .models import AuditLog


def _client_ip(request) -> str | None:
    forwarded = (request.META.get('HTTP_X_FORWARDED_FOR') or '').strip()
    if forwarded:
        # First hop is the original client when behind a proxy.
        return forwarded.split(',')[0].strip() or None
    return (request.META.get('REMOTE_ADDR') or '').strip() or None


def _user_agent(request) -> str:
    return (request.META.get('HTTP_USER_AGENT') or '')[:400]


def log_audit(
    request,
    action: str,
    *,
    message: str = '',
    actor=None,
    subject=None,
    job=None,
    details: dict | None = None,
) -> AuditLog | None:
    """Write one audit row. Never raises — logging must not break the app."""
    try:
        if actor is None and getattr(request, 'user', None) is not None:
            if request.user.is_authenticated:
                actor = request.user

        job_id = None
        job_reference = ''
        job_location = ''
        if job is not None:
            job_id = getattr(job, 'pk', None)
            job_reference = (getattr(job, 'reference', None) or '')[:100]
            job_location = (
                getattr(job, 'geocode_display', None)
                or getattr(job, 'location', None)
                or ''
            )[:255]

        return AuditLog.objects.create(
            actor=actor,
            subject=subject,
            action=action,
            message=(message or '')[:500],
            details=details or {},
            job_id=job_id,
            job_reference=job_reference,
            job_location=job_location,
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except Exception:
        return None
