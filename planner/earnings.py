"""Earnings helpers from job work types / outcomes."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from .models import Job

ZERO = Decimal('0.00')


def nominal_rate(job: Job) -> Decimal:
    """Full work-type rate, ignoring outcome."""
    return job.work_rate if job.work_rate is not None else ZERO


def earned_amount(job: Job) -> Decimal:
    """What this job contributes to earnings."""
    if job.status in (Job.Status.FAILED, Job.Status.SKIPPED):
        return ZERO
    if job.status == Job.Status.MPU:
        return Job.MPU_RATE
    if job.status == Job.Status.DONE:
        return nominal_rate(job)
    return ZERO


def projected_amount(job: Job) -> Decimal:
    """
    What this job should have paid at full work-type rate.

    Ignores outcome (fail / MPU / pending) so the day total is the pack value.
    """
    if job.status == Job.Status.SKIPPED:
        return ZERO
    return nominal_rate(job)


def summarise_jobs(jobs: Iterable[Job]) -> dict:
    jobs = list(jobs)
    projected = sum((projected_amount(j) for j in jobs), ZERO)
    earned = sum((earned_amount(j) for j in jobs), ZERO)
    failed = [j for j in jobs if j.status == Job.Status.FAILED]
    forfeited = sum((nominal_rate(j) for j in failed), ZERO)
    pending = sum(1 for j in jobs if j.status == Job.Status.PENDING)
    completed = sum(1 for j in jobs if j.status == Job.Status.DONE)
    mpu_count = sum(1 for j in jobs if j.status == Job.Status.MPU)
    mpu_earned = sum(
        (Job.MPU_RATE for j in jobs if j.status == Job.Status.MPU),
        ZERO,
    )
    return {
        'projected': projected,
        'earned': earned,
        'forfeited': forfeited,
        'failed_count': len(failed),
        'pending_count': pending,
        'completed_count': completed,
        'mpu_count': mpu_count,
        'mpu_earned': mpu_earned,
        'job_count': len(jobs),
        'projected_display': f'£{projected:.2f}',
        'earned_display': f'£{earned:.2f}',
        'forfeited_display': f'£{forfeited:.2f}',
        'mpu_display': f'£{mpu_earned:.2f}',
    }


def jobs_for_range(user, start: date, end: date):
    return (
        Job.objects.filter(user=user, job_date__gte=start, job_date__lte=end)
        .exclude(status=Job.Status.SKIPPED)
        .order_by('job_date', 'route_order', 'id')
    )


def daily_breakdown(user, start: date, end: date) -> list[dict]:
    """One summary row per date that has jobs in range."""
    jobs = list(jobs_for_range(user, start, end))
    by_day: dict[date, list[Job]] = {}
    for job in jobs:
        by_day.setdefault(job.job_date, []).append(job)

    rows = []
    day = start
    while day <= end:
        day_jobs = by_day.get(day, [])
        if day_jobs:
            summary = summarise_jobs(day_jobs)
            rows.append({'date': day, 'jobs': day_jobs, **summary})
        day += timedelta(days=1)
    return rows
