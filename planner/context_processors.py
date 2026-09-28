from .acting import active_user, get_view_as_user
from .planner_day import unresolved_previous_jobs


def view_as_context(request):
    viewed = get_view_as_user(request)
    return {
        'view_as_user': viewed,
    }


def unresolved_jobs_context(request):
    """Expose leftover previous-day pending jobs for the blocking closeout UI."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {
            'unresolved_previous_jobs': [],
            'unresolved_previous_count': 0,
        }
    planner = active_user(request)
    qs = unresolved_previous_jobs(planner)
    count = qs.count()
    jobs = list(qs[:50]) if count else []
    return {
        'unresolved_previous_jobs': jobs,
        'unresolved_previous_count': count,
    }
