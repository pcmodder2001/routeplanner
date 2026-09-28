"""Planner 'working day' — rolls to the next calendar date after 21:00 local."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.utils import timezone

# Jobs pasted after this hour belong to tomorrow's route
# (company portal drops overnight work around then).
DAY_ROLLOVER_HOUR = 21  # 9pm


def planner_today(now: datetime | None = None) -> date:
    """
    Active planning date.

    Before 21:00 → today's calendar date.
    From 21:00 onwards → tomorrow (e.g. 13 Sep 21:30 → 14 Sep).
    """
    current = timezone.localtime(now) if now is not None else timezone.localtime()
    if current.hour >= DAY_ROLLOVER_HOUR:
        return current.date() + timedelta(days=1)
    return current.date()


def planner_day_label(day: date | None = None) -> str:
    day = day or planner_today()
    return day.strftime('%a %-d %b').replace(' 0', ' ')  # Windows-safe below


def format_planner_day(day: date | None = None) -> str:
    day = day or planner_today()
    # %#d on Windows, %-d on Unix — use day.day for portability
    return f'{day.strftime("%a")} {day.day} {day.strftime("%b %Y")}'


def is_rolled_to_tomorrow(now: datetime | None = None) -> bool:
    current = timezone.localtime(now) if now is not None else timezone.localtime()
    return current.hour >= DAY_ROLLOVER_HOUR


def previous_planner_day(now: datetime | None = None) -> date:
    """Calendar day just before the active planner day (the day being closed out)."""
    return planner_today(now) - timedelta(days=1)


def unresolved_previous_jobs(user, now: datetime | None = None):
    """
    Pending jobs from before the active planner day.

    After 9pm (and any later day until cleared), engineers must mark these
    Complete / Fail / MPU before using the planner normally.
    """
    from .models import Job

    if user is None or not getattr(user, 'is_authenticated', False):
        return Job.objects.none()
    day = planner_today(now)
    return (
        Job.objects.filter(
            user=user,
            job_date__lt=day,
            status=Job.Status.PENDING,
        )
        .order_by('job_date', 'route_order', 'id')
    )


def week_bounds(day: date) -> tuple[date, date]:
    """Monday–Sunday week containing day."""
    start = day - timedelta(days=day.weekday())
    end = start + timedelta(days=6)
    return start, end
