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


def week_bounds(day: date) -> tuple[date, date]:
    """Monday–Sunday week containing day."""
    start = day - timedelta(days=day.weekday())
    end = start + timedelta(days=6)
    return start, end
