"""Superuser 'view as' — browse another engineer's jobs/route as they see them."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404

SESSION_KEY = 'view_as_user_id'
User = get_user_model()


def get_view_as_user(request):
    """Return the user being viewed, or None."""
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return None
    if not request.user.is_superuser:
        return None
    uid = request.session.get(SESSION_KEY)
    if not uid:
        return None
    try:
        other = User.objects.get(pk=uid, is_active=True)
    except User.DoesNotExist:
        request.session.pop(SESSION_KEY, None)
        return None
    if other.pk == request.user.pk:
        request.session.pop(SESSION_KEY, None)
        return None
    return other


def active_user(request):
    """User whose planner data to show/edit (view-as target or signed-in user)."""
    viewed = get_view_as_user(request)
    return viewed or request.user


def set_view_as(request, user_id: int):
    if not request.user.is_superuser:
        raise PermissionError('Only superusers can view as another user.')
    other = get_object_or_404(User, pk=user_id, is_active=True)
    if other.pk == request.user.pk:
        request.session.pop(SESSION_KEY, None)
        return None
    request.session[SESSION_KEY] = other.pk
    return other


def clear_view_as(request):
    request.session.pop(SESSION_KEY, None)


def list_engineers():
    return User.objects.filter(is_active=True).order_by('username')
