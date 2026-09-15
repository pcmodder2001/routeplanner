"""Parse work-pack paste blocks into job fields."""

from __future__ import annotations

import re
from typing import Any

from .models import Job

# Split whenever a new Jin appears (start of a job block)
_JIN_SPLIT = re.compile(r'(?=Jin\s*no\s*:)', re.IGNORECASE)

_FIELD = {
    'jin': re.compile(r'Jin\s*no\s*:\s*(.+)', re.IGNORECASE),
    'slot': re.compile(r'Time\s*slot\s*:\s*(.+)', re.IGNORECASE),
    'job_type': re.compile(r'JobType\s*:\s*(.+)', re.IGNORECASE),
    'address': re.compile(r'Address\s*:\s*(.+)', re.IGNORECASE),
    'postcode': re.compile(r'Postcode\s*:\s*(.+)', re.IGNORECASE),
    'task_description': re.compile(r'Task\s*Description\s*:\s*(.+)', re.IGNORECASE),
    'task_name': re.compile(r'Task\s*Name\s*:\s*(.+)', re.IGNORECASE),
}

_MAPS_NOISE = re.compile(
    r'\s*(Google\s*Maps|WAZE|Waze).*$',
    re.IGNORECASE,
)

# UK postcode (outward + inward), case-insensitive
_UK_POSTCODE = re.compile(
    r'\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b',
    re.IGNORECASE,
)


def jin_to_reference(jin: str) -> str:
    """Keep everything after the first hyphen (e.g. YO-MY5699295 → MY5699295)."""
    jin = (jin or '').strip()
    if '-' in jin:
        return jin.split('-', 1)[1].strip()
    return jin


def normalise_reference(ref: str) -> str:
    return re.sub(r'\s+', '', (ref or '').strip().upper())


def normalise_postcode(pc: str) -> str:
    """Uppercase with a single space before the inward code (e.g. HX78QU → HX7 8QU)."""
    compact = re.sub(r'[^A-Z0-9]', '', (pc or '').upper())
    if len(compact) < 5:
        return compact
    return f'{compact[:-3]} {compact[-3:]}'


def extract_uk_postcode(text: str) -> str:
    """Return the last UK postcode found in text, normalised, or ''."""
    matches = _UK_POSTCODE.findall(text or '')
    if not matches:
        return ''
    return normalise_postcode(matches[-1])


def parse_time_slot(raw: str) -> str:
    text = (raw or '').strip().upper()
    if not text:
        return Job.AppointmentType.ALLDAY
    if 'ALL' in text:
        return Job.AppointmentType.ALLDAY
    # Whole-word / leading AM or PM (avoids matching inside other words)
    if re.search(r'\bAM\b', text) or text.startswith('AM'):
        return Job.AppointmentType.AM
    if re.search(r'\bPM\b', text) or text.startswith('PM'):
        return Job.AppointmentType.PM
    return Job.AppointmentType.ALLDAY


def parse_work_type(
    task_description: str,
    task_name: str = '',
    job_type: str = '',
) -> dict[str, Any]:
    """
    Classify task text into a work type + pay rate.

    Priority: self install → managed install → copper / FTTC·OGEA / SOGEA repair.
    FTTC fault / FTTCT2R counts as OGEA repair (£30).
    """
    blob = f'{task_description or ""} {task_name or ""} {job_type or ""}'.upper()
    blob = blob.replace('|', ' ')
    blob = re.sub(r'\s+', ' ', blob).strip()

    if not blob:
        return {
            'work_type': '',
            'work_type_label': '',
            'rate': '',
        }

    def result(work_type: str) -> dict[str, Any]:
        rate = Job.WORK_TYPE_RATES.get(work_type)
        return {
            'work_type': work_type,
            'work_type_label': dict(Job.WorkType.choices).get(work_type, ''),
            'rate': f'{rate:.2f}' if rate is not None else '',
        }

    if 'SELF INSTALL' in blob or 'SELF-INSTALL' in blob or 'SELFINSTALL' in blob:
        return result(Job.WorkType.SELF_INSTALL)
    if 'MANAGED INSTALL' in blob or 'MANAGEDINSTALL' in blob:
        return result(Job.WorkType.MANAGED_INSTALL)
    if 'COPPER' in blob and ('REPAIR' in blob or 'FAULT' in blob):
        return result(Job.WorkType.COPPER_REPAIR)
    if 'COPPER' in blob:
        return result(Job.WorkType.COPPER_REPAIR)
    # FTTCFault / FTTC fault / FTTCT2R — same pay band as OGEA repair
    if 'FTTC' in blob:
        return result(Job.WorkType.OGEA_REPAIR)
    # OGEA without a leading S (so SOGEA does not match)
    if re.search(r'(?<!S)OGEA', blob):
        return result(Job.WorkType.OGEA_REPAIR)
    if 'SOGEA' in blob and ('REPAIR' in blob or 'FAULT' in blob):
        return result(Job.WorkType.SOGEA_REPAIR)
    if 'SOGEA' in blob and 'NEW LINE' in blob:
        # New provide without explicit managed/self — leave blank rather than guess
        return {
            'work_type': '',
            'work_type_label': '',
            'rate': '',
        }
    if 'SOGEA' in blob:
        return result(Job.WorkType.SOGEA_REPAIR)

    return {
        'work_type': '',
        'work_type_label': '',
        'rate': '',
    }


def clean_postcode(raw: str) -> str:
    text = (raw or '').strip()
    text = _MAPS_NOISE.sub('', text).strip()
    # Trailing punctuation / map links
    text = re.sub(r'[,;]+$', '', text).strip()
    extracted = extract_uk_postcode(text)
    return extracted or text


def build_location(address: str, postcode: str) -> str:
    address = (address or '').strip().rstrip(',').strip()
    postcode = clean_postcode(postcode)
    if postcode and address and extract_uk_postcode(address) == normalise_postcode(
        postcode
    ):
        return address
    if postcode and address and postcode.upper() in address.upper():
        return address
    if address and postcode:
        return f'{address}, {postcode}'
    return address or postcode


def job_postcode(job: Job) -> str:
    """Best postcode guess from a stored job."""
    for text in (job.geocode_display, job.location):
        pc = extract_uk_postcode(text or '')
        if pc:
            return pc
    return ''


def pending_route_index(user) -> dict[str, Any]:
    """
    Index pending jobs for bulk sync / duplicate checks (planner day only).
    """
    from .planner_day import planner_today

    jobs = list(
        Job.objects.filter(
            user=user,
            job_date=planner_today(),
            status=Job.Status.PENDING,
        ).order_by('route_order', 'id')
    )
    summaries = []
    by_ref: dict[str, dict[str, Any]] = {}
    by_postcode: dict[str, list[dict[str, Any]]] = {}
    for job in jobs:
        pc = job_postcode(job)
        summary = {
            'id': job.id,
            'reference': (job.reference or '').strip(),
            'location': job.geocode_display or job.location,
            'appointment_type': job.appointment_type,
            'postcode': pc,
        }
        summaries.append(summary)
        ref_key = normalise_reference(job.reference or '')
        if ref_key and ref_key not in by_ref:
            by_ref[ref_key] = summary
        if pc:
            by_postcode.setdefault(pc, []).append(summary)
    return {
        'jobs': summaries,
        'by_ref': by_ref,
        'by_postcode': by_postcode,
    }


def find_duplicate_postcode_jobs(user, location: str, *, exclude_id: int | None = None):
    """Pending jobs on the planner day that already use the same postcode."""
    from .planner_day import planner_today

    pc = extract_uk_postcode(location)
    if not pc:
        return pc, []
    matches = []
    for job in Job.objects.filter(
        user=user,
        job_date=planner_today(),
        status=Job.Status.PENDING,
    ):
        if exclude_id and job.id == exclude_id:
            continue
        if job_postcode(job) == pc:
            matches.append(job)
    return pc, matches


def diff_bulk_against_route(parsed_jobs: list[dict[str, Any]], user) -> dict[str, Any]:
    """
    Compare pasted jobs with pending route jobs.

    - to_add: in paste, not on route (by job reference)
    - already_on: in paste and already on route
    - missing_from_paste: on route, not in paste (candidates to remove)
    - postcode_warnings: new jobs whose postcode is already on the route
    """
    index = pending_route_index(user)
    paste_refs = {
        normalise_reference(j['reference'])
        for j in parsed_jobs
        if normalise_reference(j.get('reference') or '')
    }

    to_add: list[dict[str, Any]] = []
    already_on: list[dict[str, Any]] = []
    seen_refs: set[str] = set()

    for job in parsed_jobs:
        ref_key = normalise_reference(job.get('reference') or '')
        if not ref_key:
            to_add.append(job)
            continue
        if ref_key in seen_refs:
            continue
        seen_refs.add(ref_key)
        if ref_key in index['by_ref']:
            existing = index['by_ref'][ref_key]
            already_on.append(
                {
                    **job,
                    'existing_id': existing['id'],
                    'existing_location': existing['location'],
                }
            )
        else:
            to_add.append(job)

    missing_from_paste: list[dict[str, Any]] = []
    if parsed_jobs:
        for j in index['jobs']:
            ref_key = normalise_reference(j.get('reference') or '')
            if not ref_key or ref_key not in paste_refs:
                missing_from_paste.append(j)

    postcode_warnings: list[dict[str, str]] = []
    warned_pcs: set[str] = set()
    for job in to_add:
        pc = normalise_postcode(job.get('postcode') or '') or extract_uk_postcode(
            job.get('location') or ''
        )
        if not pc or pc in warned_pcs:
            continue
        existing_at_pc = index['by_postcode'].get(pc) or []
        if existing_at_pc:
            warned_pcs.add(pc)
            refs = ', '.join(
                (e['reference'] or e['location']) for e in existing_at_pc[:3]
            )
            postcode_warnings.append(
                {
                    'postcode': pc,
                    'message': f'{pc} job already on route'
                    + (f' ({refs})' if refs else ''),
                }
            )

    return {
        'to_add': to_add,
        'already_on': already_on,
        'missing_from_paste': missing_from_paste,
        'postcode_warnings': postcode_warnings,
    }


def _first_match(pattern: re.Pattern[str], block: str) -> str:
    m = pattern.search(block)
    if not m:
        return ''
    return m.group(1).strip()


def parse_job_block(block: str) -> dict[str, Any] | None:
    """Parse one Jin block. Returns None if no usable Jin / location."""
    block = (block or '').strip()
    if not block:
        return None

    jin = _first_match(_FIELD['jin'], block)
    if not jin:
        return None

    reference = jin_to_reference(jin)
    slot_raw = _first_match(_FIELD['slot'], block)
    appointment_type = parse_time_slot(slot_raw)
    address = _first_match(_FIELD['address'], block)
    postcode = clean_postcode(_first_match(_FIELD['postcode'], block))
    location = build_location(address, postcode)
    task_description = _first_match(_FIELD['task_description'], block)
    task_name = _first_match(_FIELD['task_name'], block)
    job_type = _first_match(_FIELD['job_type'], block)
    work = parse_work_type(task_description, task_name, job_type)

    errors: list[str] = []
    if not reference:
        errors.append('Missing job number after Jin hyphen')
    if not location:
        errors.append('Missing address / postcode')

    return {
        'jin': jin,
        'reference': reference,
        'appointment_type': appointment_type,
        'slot_raw': slot_raw,
        'address': address,
        'postcode': postcode,
        'location': location,
        'task_description': task_description,
        'task_name': task_name,
        'work_type': work['work_type'],
        'work_type_label': work['work_type_label'],
        'rate': work['rate'],
        'errors': errors,
        'ok': not errors,
    }


def parse_bulk_jobs(raw: str) -> dict[str, Any]:
    """
    Parse pasted multi-job text.

    Returns:
      {
        'jobs': [valid job dicts],
        'invalid': [job dicts with errors],
        'count': int,
      }
    """
    text = (raw or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if not text:
        return {'jobs': [], 'invalid': [], 'count': 0}

    parts = _JIN_SPLIT.split(text)
    jobs: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []

    for part in parts:
        parsed = parse_job_block(part)
        if not parsed:
            continue
        if parsed['ok']:
            jobs.append(parsed)
        else:
            invalid.append(parsed)

    return {
        'jobs': jobs,
        'invalid': invalid,
        'count': len(jobs),
    }
