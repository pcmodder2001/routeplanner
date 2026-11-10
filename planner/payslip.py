"""Compare a pasted payment list with jobs already in the planner.

Paste shape (one payment, five lines, blank lines ignored):

    30/10/2026
    YO-MY6021791
    BBR-COM Broadband Repair Com
    £ 40.00
    13/11/2026

Nothing is stored. Job numbers match with or without the prefix
(YO-MY6021791 and MY6021791 are the same job).
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable

from .bulk_parse import jin_to_reference, normalise_reference
from .earnings import nominal_rate
from .models import Job

ZERO = Decimal('0.00')
_PAYSLIP_LISTS = (
    'pay_conflicts',
    'not_in_planner',
    'missing_from_payslip',
    'adjustments',
    'warnings',
    'duplicates',
    'matched',
)


def money(amount: Decimal) -> str:
    amount = Decimal(amount).quantize(Decimal('0.01'))
    if amount < 0:
        return f'-£{abs(amount):.2f}'
    return f'£{amount:.2f}'


def fmt_date(value: date | None) -> str:
    if not value:
        return ''
    return value.strftime('%d/%m/%Y')


def parse_uk_date(text: str) -> date | None:
    match = re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{4})', (text or '').strip())
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_amount(text: str) -> Decimal | None:
    raw = (text or '').strip().replace('\u00a0', '').replace(' ', '')
    raw = raw.replace('−', '-').replace('–', '-').replace('—', '-')
    raw = raw.replace('£', '').replace(',', '')
    if not re.fullmatch(r'-?\d+(?:\.\d{1,2})?', raw or ''):
        return None
    try:
        return Decimal(raw).quantize(Decimal('0.01'))
    except InvalidOperation:
        return None


def reference_keys(raw: str) -> set[str]:
    """Keys that should match a planner reference for this job number."""
    text = (raw or '').strip()
    keys = set()
    full = normalise_reference(text)
    short = normalise_reference(jin_to_reference(text))
    if full:
        keys.add(full)
    if short:
        keys.add(short)
    return keys


def _lines(raw: str) -> list[str]:
    cleaned = (raw or '').replace('\u00a0', ' ')
    return [line.strip() for line in cleaned.splitlines() if line.strip()]


def _take_record(lines: list[str], index: int) -> dict | None:
    if index + 4 >= len(lines):
        return None
    job_date = parse_uk_date(lines[index])
    reference = lines[index + 1].strip()
    description = lines[index + 2].strip()
    amount = parse_amount(lines[index + 3])
    paid_date = parse_uk_date(lines[index + 4])
    if not job_date or not paid_date or amount is None or not reference:
        return None
    if parse_uk_date(reference) or parse_uk_date(description):
        return None
    if '£' in description and parse_amount(description) is not None:
        return None
    return {
        'job_date': job_date,
        'reference': reference,
        'description': description,
        'amount': amount,
        'paid_date': paid_date,
    }


def parse_payslip(raw: str) -> tuple[list[dict], list[str]]:
    """Return payment rows and human-readable lines that did not fit."""
    lines = _lines(raw)
    records: list[dict] = []
    errors: list[str] = []
    index = 0
    while index < len(lines):
        record = _take_record(lines, index)
        if record is None:
            snippet = lines[index][:80]
            errors.append(f'Skipped “{snippet}”.')
            index += 1
            continue
        records.append(record)
        index += 5
    if len(errors) > 8:
        extra = len(errors) - 8
        errors = errors[:8]
        errors.append(f'…and {extra} more skipped lines.')
    return records, errors


def looks_like_adjustment(record: dict) -> bool:
    """Clawbacks and incomplete-work lines, not a normal job payment."""
    if record['amount'] < 0:
        return True
    return 'INCOMPLETE' in (record.get('description') or '').upper()


def expected_pay(job: Job) -> Decimal:
    """Amount this job should show on a payslip."""
    if job.status == Job.Status.MPU:
        return Job.MPU_RATE
    if job.status in (Job.Status.FAILED, Job.Status.SKIPPED):
        return ZERO
    return nominal_rate(job)


def _job_ident(job: Job):
    if job.pk:
        return ('pk', job.pk)
    return ('obj', id(job))


def _index_jobs(jobs: Iterable[Job]) -> dict[str, list[Job]]:
    index: dict[str, list[Job]] = {}
    for job in jobs:
        for key in reference_keys(job.reference or ''):
            index.setdefault(key, []).append(job)
    return index


def _lookup(index: dict[str, list[Job]], reference: str) -> list[Job]:
    found: list[Job] = []
    seen = set()
    for key in reference_keys(reference):
        for job in index.get(key, []):
            ident = _job_ident(job)
            if ident in seen:
                continue
            seen.add(ident)
            found.append(job)
    return found


def _choose(candidates: list[Job], job_date: date) -> Job:
    def sort_key(job: Job):
        if job.job_date:
            distance = abs((job.job_date - job_date).days)
        else:
            distance = 9999
        return (distance, job.pk or 0)

    return min(candidates, key=sort_key)


def _pay_sentence(job: Job, paid: Decimal, expected: Decimal) -> str:
    status = job.get_status_display()
    if job.status == Job.Status.MPU:
        return f'Payslip {money(paid)}, planner has MPU {money(expected)}'
    if not job.work_type:
        return f'Payslip {money(paid)}, planner has {status} with no rate set'
    label = job.work_type_label or 'job'
    return (
        f'Payslip {money(paid)}, planner has {status} {label} {money(expected)}'
    )


def _base_row(record: dict, job: Job | None = None) -> dict:
    row = {
        'reference': record['reference'],
        'link_ref': jin_to_reference(record['reference']),
        'job_date': fmt_date(record['job_date']),
        'planner_date': '',
        'paid_date': fmt_date(record['paid_date']),
        'description': record['description'],
        'paid': money(record['amount']),
        'expected': '',
        'status': '',
        'work_type': '',
        'place': '',
        'detail': '',
    }
    if job is not None:
        row['link_ref'] = (job.reference or row['link_ref'] or '').strip()
        row['planner_date'] = fmt_date(job.job_date)
        row['expected'] = money(expected_pay(job))
        row['status'] = job.get_status_display()
        row['work_type'] = job.work_type_label or '—'
        row['place'] = (job.geocode_display or job.location or '').strip()
    return row


def _job_row(job: Job) -> dict:
    return {
        'reference': (job.reference or '').strip() or '—',
        'link_ref': (job.reference or '').strip(),
        'job_date': fmt_date(job.job_date),
        'planner_date': fmt_date(job.job_date),
        'paid_date': '',
        'description': '',
        'paid': '',
        'expected': money(expected_pay(job)),
        'status': job.get_status_display(),
        'work_type': job.work_type_label or '—',
        'place': (job.geocode_display or job.location or '').strip(),
        'detail': 'Completed in the planner but not on this payslip',
    }


def reconcile_payslip(raw: str, jobs: Iterable[Job]) -> dict:
    """Match pasted payments to jobs. Does not write anything."""
    records, parse_errors = parse_payslip(raw)
    if not records:
        return {
            'ok': False,
            'error': (
                'No payment lines found. Each job needs a date, job number, '
                'description, amount, and payment date.'
            ),
            'parse_errors': parse_errors,
        }

    index = _index_jobs(jobs)
    used = set()
    buckets = {name: [] for name in _PAYSLIP_LISTS}

    for record in records:
        hits = _lookup(index, record['reference'])
        unused = [job for job in hits if _job_ident(job) not in used]
        if not hits:
            row = _base_row(record)
            if looks_like_adjustment(record):
                row['detail'] = 'Deduction with no matching job number'
                buckets['adjustments'].append(row)
            else:
                row['detail'] = 'No job with this number'
                buckets['not_in_planner'].append(row)
            continue
        if not unused:
            row = _base_row(record)
            row['detail'] = 'This job number is already on an earlier line'
            buckets['duplicates'].append(row)
            continue

        job = _choose(unused, record['job_date'])
        used.add(_job_ident(job))
        paid = record['amount']
        expected = expected_pay(job)
        pay_ok = paid == expected
        notes = []
        if job.job_date != record['job_date']:
            notes.append(
                f"Planner date is {fmt_date(job.job_date)}, "
                f"payslip date is {fmt_date(record['job_date'])}"
            )
        if job.status == Job.Status.PENDING:
            notes.append('Job is still pending')
        elif job.status == Job.Status.FAILED:
            notes.append('Job is marked failed')
        elif job.status == Job.Status.SKIPPED:
            notes.append('Job is marked skipped')
        same_day_others = [
            other
            for other in unused
            if other is not job and other.job_date == job.job_date
        ]
        if same_day_others:
            notes.append('Another planner job has the same number on this date')

        row = _base_row(record, job)
        if not pay_ok:
            parts = [_pay_sentence(job, paid, expected), *notes]
            row['detail'] = '. '.join(parts)
            buckets['pay_conflicts'].append(row)
        elif notes:
            row['detail'] = '. '.join(notes)
            buckets['warnings'].append(row)
        else:
            row['detail'] = 'Pay matches'
            buckets['matched'].append(row)

    span = [record['job_date'] for record in records if not looks_like_adjustment(record)]
    window_from = ''
    window_to = ''
    window_label = ''
    if span:
        start, end = min(span), max(span)
        window_from = fmt_date(start)
        window_to = fmt_date(end)
        if start == end:
            window_label = (
                f'Completed and MPU jobs on {window_from} are checked against this paste.'
            )
        else:
            window_label = (
                f'Completed and MPU jobs from {window_from} to {window_to} '
                'are checked against this paste.'
            )
        payable = {Job.Status.DONE, Job.Status.MPU}
        missing = [
            job
            for job in jobs
            if job.job_date
            and start <= job.job_date <= end
            and job.status in payable
            and _job_ident(job) not in used
        ]
        missing.sort(key=lambda job: (job.job_date, job.reference or '', job.pk or 0))
        buckets['missing_from_payslip'] = [_job_row(job) for job in missing]

    issue_count = (
        len(buckets['pay_conflicts'])
        + len(buckets['not_in_planner'])
        + len(buckets['missing_from_payslip'])
        + len(buckets['warnings'])
        + len(buckets['duplicates'])
    )
    total = sum((record['amount'] for record in records), ZERO)
    result = {
        'ok': True,
        'parse_errors': parse_errors,
        'summary': {
            'parsed': len(records),
            'matched': len(buckets['matched']),
            'pay_conflicts': len(buckets['pay_conflicts']),
            'not_in_planner': len(buckets['not_in_planner']),
            'missing_from_payslip': len(buckets['missing_from_payslip']),
            'adjustments': len(buckets['adjustments']),
            'warnings': len(buckets['warnings']),
            'duplicates': len(buckets['duplicates']),
            'issue_count': issue_count,
            'payslip_total': money(total),
            'window_from': window_from,
            'window_to': window_to,
            'window_label': window_label,
        },
    }
    result.update(buckets)
    return result
