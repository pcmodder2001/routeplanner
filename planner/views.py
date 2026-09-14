from datetime import date, datetime, timedelta
from decimal import Decimal

import json

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .acting import (
    active_user,
    clear_view_as,
    list_engineers,
    set_view_as,
)
from .audit import log_audit
from .bulk_parse import (
    diff_bulk_against_route,
    extract_uk_postcode,
    find_duplicate_postcode_jobs,
    job_postcode,
    parse_bulk_jobs,
    parse_time_slot,
)
from .earnings import daily_breakdown, summarise_jobs
from .forms import (
    AppointmentTypeForm,
    JobForm,
    JobNotesForm,
    LoginForm,
    RegisterForm,
    SettingsForm,
    VanKitBulkForm,
    VanKitItemForm,
    VanKitScanForm,
)
from .geocoding import (
    address_autocomplete,
    address_lookup_enabled,
    geocode_location,
    google_geocode,
    google_maps_key,
    google_place_details,
    paf_lookup_enabled,
)
from .models import BulkPasteLog, DayRoute, EngineerSettings, Job, VanKitItem, AuditLog
from .osrm import active_routing_label
from .planner_day import (
    format_planner_day,
    is_rolled_to_tomorrow,
    planner_today,
    week_bounds,
)
from .routing import (
    PlannedStop,
    apply_manual_order,
    clear_current_route,
    google_maps_url,
    next_job_navigate_url,
    plan_current_route,
    set_job_status,
)


REMEMBER_ME_SECONDS = 60 * 60 * 24 * 90  # 90 days


def _user_job(request, pk: int) -> Job:
    return get_object_or_404(Job, pk=pk, user=active_user(request))


def _superuser_required(user):
    return user.is_authenticated and user.is_superuser


@require_http_methods(['GET', 'POST'])
def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    form = LoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = authenticate(
            request,
            username=form.cleaned_data['username'],
            password=form.cleaned_data['password'],
        )
        if user is None:
            log_audit(
                request,
                AuditLog.Action.LOGIN_FAILED,
                message=f'Failed login for “{form.cleaned_data["username"]}”',
                details={'username': form.cleaned_data['username']},
            )
            messages.error(request, 'Invalid username or password.')
        elif not user.is_active:
            log_audit(
                request,
                AuditLog.Action.LOGIN_FAILED,
                message=f'Disabled account login: {user.username}',
                actor=user,
                details={'username': user.username, 'reason': 'disabled'},
            )
            messages.error(request, 'This account is disabled.')
        else:
            login(request, user)
            clear_view_as(request)
            if form.cleaned_data.get('remember_me'):
                request.session.set_expiry(REMEMBER_ME_SECONDS)
            else:
                request.session.set_expiry(0)  # until browser closes
            EngineerSettings.for_user(user)
            log_audit(
                request,
                AuditLog.Action.LOGIN,
                message=f'{user.username} signed in',
                actor=user,
                details={'remember_me': bool(form.cleaned_data.get('remember_me'))},
            )
            next_url = request.GET.get('next') or request.POST.get('next') or '/'
            if not next_url.startswith('/'):
                next_url = '/'
            return redirect(next_url)

    return render(
        request,
        'planner/login.html',
        {
            'form': form,
            'next': request.GET.get('next', ''),
        },
    )


@require_http_methods(['GET', 'POST'])
def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        clear_view_as(request)
        if form.cleaned_data.get('remember_me'):
            request.session.set_expiry(REMEMBER_ME_SECONDS)
        else:
            request.session.set_expiry(0)
        EngineerSettings.for_user(user)
        log_audit(
            request,
            AuditLog.Action.REGISTER,
            message=f'Account created: {user.username}',
            actor=user,
        )
        messages.success(request, f'Welcome, {user.username} — account created.')
        return redirect('dashboard')

    return render(request, 'planner/register.html', {'form': form})


@require_POST
def logout_view(request):
    user = request.user if request.user.is_authenticated else None
    username = user.username if user else 'anonymous'
    log_audit(
        request,
        AuditLog.Action.LOGOUT,
        message=f'{username} signed out',
        actor=user,
    )
    clear_view_as(request)
    logout(request)
    messages.info(request, 'Signed out.')
    return redirect('login')


@login_required
@user_passes_test(_superuser_required)
def engineers_view(request):
    engineers = list_engineers().annotate(
        pending_count=Count('jobs', filter=Q(jobs__status=Job.Status.PENDING)),
        job_count=Count('jobs'),
    )
    return render(
        request,
        'planner/engineers.html',
        {
            'engineers': engineers,
        },
    )


@login_required
@user_passes_test(_superuser_required)
@require_POST
def view_as_user(request, user_id: int):
    other = set_view_as(request, user_id)
    if other is None:
        messages.info(request, 'Viewing your own account.')
    else:
        log_audit(
            request,
            AuditLog.Action.VIEW_AS,
            message=f'Viewing as {other.username}',
            subject=other,
        )
        messages.info(request, f'Viewing as {other.username}.')
    return redirect('dashboard')


@login_required
@user_passes_test(_superuser_required)
@require_POST
def stop_view_as(request):
    viewed = active_user(request)
    log_audit(
        request,
        AuditLog.Action.STOP_VIEW_AS,
        message='Stopped view-as',
        subject=viewed if viewed.pk != request.user.pk else None,
    )
    clear_view_as(request)
    messages.info(request, 'Back to your own account.')
    return redirect('dashboard')


@login_required
def dashboard(request):
    planner = active_user(request)
    day = planner_today()
    jobs = Job.objects.filter(user=planner, job_date=day).order_by(
        'status',
        'route_order',
        'appointment_type',
        'id',
    )
    pending = [j for j in jobs if j.status == Job.Status.PENDING]
    pending_ordered = sorted(
        [j for j in pending if j.route_order is not None],
        key=lambda j: j.route_order or 0,
    )
    pending_rest = [j for j in pending if j.route_order is None]
    finished = [j for j in jobs if j.status != Job.Status.PENDING]
    display_jobs = pending_ordered + pending_rest + finished

    settings = EngineerSettings.for_user(planner)
    planned = pending_ordered
    day_route = DayRoute.objects.filter(user=planner, job_date=day).first()
    earnings = summarise_jobs(jobs)
    total_miles = (
        day_route.total_miles
        if day_route
        else round(sum(j.leg_miles_from_previous or 0 for j in planned), 1)
    )
    total_minutes = (
        day_route.total_minutes
        if day_route
        else sum(j.leg_minutes_from_previous or 0 for j in planned)
    )

    map_points = []
    if settings.start_lat is not None and settings.start_lng is not None:
        map_points.append(
            {
                'order': 0,
                'label': settings.start_display
                or settings.start_location
                or settings.start_label
                or 'Start',
                'lat': settings.start_lat,
                'lng': settings.start_lng,
                'type': 'START',
                'status': 'start',
            }
        )
    # Full day on the map: planned order, then unplanned pending, then
    # finished jobs that lost route_order (older Done/Skip cleared it).
    map_jobs = sorted(
        [j for j in jobs if j.is_geocoded and j.route_order is not None],
        key=lambda j: j.route_order or 0,
    )
    map_jobs.extend(j for j in pending_rest if j.is_geocoded)
    seen = {j.id for j in map_jobs}
    map_jobs.extend(
        j
        for j in finished
        if j.is_geocoded and j.id not in seen
    )
    for job in map_jobs:
        map_points.append(
            {
                'order': job.route_order,
                'label': job.geocode_display
                or job.reference
                or job.location,
                'lat': job.lat,
                'lng': job.lng,
                'type': job.appointment_type,
                'status': job.status,
            }
        )

    stops_for_maps = []
    if settings.start_lat is not None and settings.start_lng is not None:
        stops_for_maps.append(
            PlannedStop(
                order=0,
                job=None,
                label='Start',
                appointment='START',
                lat=settings.start_lat,
                lng=settings.start_lng,
                miles_from_previous=0,
                minutes_from_previous=0,
                estimated_arrival=None,
                is_start=True,
            )
        )
    for job in map_jobs:
        stops_for_maps.append(
            PlannedStop(
                order=job.route_order or 0,
                job=job,
                label=job.location,
                appointment=job.appointment_type,
                lat=job.lat,
                lng=job.lng,
                miles_from_previous=job.leg_miles_from_previous or 0,
                minutes_from_previous=job.leg_minutes_from_previous or 0,
                estimated_arrival=job.estimated_arrival,
            )
        )

    route_geometry = day_route.geometry if day_route else []
    next_job, next_nav_url = next_job_navigate_url(planner)
    job_rows = [
        {
            'job': job,
            'appointment_form': AppointmentTypeForm(
                instance=job,
                prefix=f'appt-{job.pk}',
            ),
            'notes_form': JobNotesForm(
                instance=job,
                prefix=f'notes-{job.pk}',
            ),
        }
        for job in display_jobs
    ]

    source = day_route.source if day_route else ''
    source_label = {
        'google': 'Traffic (Google)',
        'ors': 'Road (ORS)',
        'osrm': 'Road route',
        'haversine': 'Approx',
    }.get(source, 'Ordered' if planned else '')

    context = {
        'jobs': display_jobs,
        'job_rows': job_rows,
        'settings': settings,
        'job_form': JobForm(),
        'planned_count': len(planned),
        'pending_count': len(pending),
        'total_miles': total_miles,
        'total_minutes': total_minutes,
        'map_points': map_points,
        'route_geometry': route_geometry,
        'maps_url': google_maps_url(stops_for_maps),
        'next_nav_url': next_nav_url,
        'next_job': next_job,
        'has_route': bool(planned),
        'order_locked': bool(day_route and day_route.order_locked),
        'route_source': source,
        'route_source_label': source_label,
        'routing_provider': active_routing_label(),
        'google_places_enabled': bool(google_maps_key()),
        'getaddress_enabled': paf_lookup_enabled(),
        'address_lookup_enabled': address_lookup_enabled(),
        'route_postcodes': sorted(
            {pc for j in pending if (pc := job_postcode(j))}
        ),
        'planner_day': day,
        'planner_day_label': format_planner_day(day),
        'planner_rolled': is_rolled_to_tomorrow(),
        'earnings': earnings,
    }
    return render(request, 'planner/dashboard.html', context)


@login_required
@require_GET
def places_autocomplete(request):
    query = (request.GET.get('q') or '').strip()
    token = (request.GET.get('token') or '').strip()
    if not address_lookup_enabled():
        return JsonResponse({'suggestions': [], 'enabled': False})
    suggestions = address_autocomplete(query, session_token=token)
    return JsonResponse(
        {
            'suggestions': suggestions,
            'enabled': True,
            'paf': paf_lookup_enabled(),
        }
    )


@login_required
@require_GET
def place_details(request):
    place_id = (request.GET.get('place_id') or '').strip()
    token = (request.GET.get('token') or '').strip()
    if not place_id:
        return JsonResponse({'ok': False, 'error': 'missing place_id'}, status=400)
    details = google_place_details(place_id, session_token=token)
    if not details:
        return JsonResponse({'ok': False, 'error': 'not found'}, status=404)
    return JsonResponse({'ok': True, 'place': details})


@login_required
@require_POST
def add_job(request):
    planner = active_user(request)
    form = JobForm(request.POST)
    if form.is_valid():
        job = form.save(commit=False)
        job.user = planner

        place_lat = request.POST.get('place_lat', '').strip()
        place_lng = request.POST.get('place_lng', '').strip()
        place_display = request.POST.get('place_display', '').strip()
        if place_lat and place_lng:
            try:
                job.lat = float(place_lat)
                job.lng = float(place_lng)
                job.geocode_display = (place_display or job.location)[:255]
                if place_display and google_maps_key():
                    refined = google_geocode(place_display.replace(' · ', ', '))
                    if refined and refined.get('lat') is not None:
                        job.lat = refined['lat']
                        job.lng = refined['lng']
                        job.geocode_display = refined['display'][:255]
                messages.success(request, f'Added {job.geocode_display}')
            except ValueError:
                place_lat = place_lng = ''

        if not place_lat or not place_lng:
            result = geocode_location(job.location)
            if result:
                job.lat = result['lat']
                job.lng = result['lng']
                job.geocode_display = result['display'][:255]
                messages.success(request, f'Added {result["display"]}')
            else:
                messages.warning(
                    request,
                    f'Added {job.location}, but could not geocode it yet. '
                    'Check the address/postcode.',
                )

        dup_pc, dup_jobs = find_duplicate_postcode_jobs(planner, job.location)
        if not dup_pc and job.geocode_display:
            dup_pc, dup_jobs = find_duplicate_postcode_jobs(
                planner, job.geocode_display
            )
        if dup_pc and dup_jobs:
            messages.warning(
                request,
                f'{dup_pc} job already on route.',
            )

        job.status = Job.Status.PENDING
        job.route_order = None
        job.job_date = planner_today()
        job.save()
        DayRoute.objects.filter(user=planner, job_date=job.job_date).update(
            order_locked=False
        )
        Job.objects.filter(
            user=planner, job_date=job.job_date, status=Job.Status.PENDING
        ).update(
            route_order=None,
            estimated_arrival=None,
            leg_miles_from_previous=None,
            leg_minutes_from_previous=None,
        )
        DayRoute.objects.filter(user=planner, job_date=job.job_date).delete()
        log_audit(
            request,
            AuditLog.Action.ADD_JOB,
            message=f'Added job {job.geocode_display or job.location}',
            subject=planner,
            job=job,
            details={
                'reference': job.reference,
                'appointment_type': job.appointment_type,
                'work_type': job.work_type,
                'job_date': str(job.job_date),
            },
        )
        return redirect('dashboard')

    messages.error(request, 'Could not add job — check the form.')
    return redirect('dashboard')


def _json_body(request) -> dict:
    try:
        return json.loads(request.body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _job_payload(j: dict) -> dict:
    return {
        'reference': j.get('reference') or '',
        'appointment_type': j.get('appointment_type') or '',
        'location': j.get('location') or '',
        'jin': j.get('jin') or '',
        'postcode': j.get('postcode') or extract_uk_postcode(j.get('location') or ''),
        'work_type': j.get('work_type') or '',
        'work_type_label': j.get('work_type_label') or '',
        'rate': j.get('rate') or '',
    }


def _bulk_paste_search_text(raw: str, items: list) -> str:
    """Build a searchable blob from raw paste + parsed job fields."""
    bits = [raw or '']
    for item in items or []:
        if not isinstance(item, dict):
            continue
        for key in (
            'reference',
            'jin',
            'location',
            'postcode',
            'work_type_label',
            'appointment_type',
        ):
            val = str(item.get(key) or '').strip()
            if val:
                bits.append(val)
    return ' '.join(bits).lower()


def _save_bulk_paste_log(
    *,
    request,
    planner,
    day,
    raw: str,
    items: list,
    jobs_added: int,
    jobs_removed: int,
) -> BulkPasteLog | None:
    raw = (raw or '').strip()
    if not raw:
        return None
    return BulkPasteLog.objects.create(
        user=planner,
        created_by=request.user if request.user.is_authenticated else None,
        job_date=day,
        raw_text=raw,
        search_text=_bulk_paste_search_text(raw, items),
        jobs_added=jobs_added,
        jobs_removed=jobs_removed,
    )


@login_required
@require_POST
def bulk_add_preview(request):
    """Parse pasted work-pack text and diff against the current pending route."""
    planner = active_user(request)
    body = _json_body(request)
    raw = body.get('raw') or request.POST.get('raw') or ''
    parsed = parse_bulk_jobs(raw)
    diff = diff_bulk_against_route(parsed['jobs'], planner)
    return JsonResponse(
        {
            'ok': True,
            'parsed_count': parsed['count'],
            'count': len(diff['to_add']),
            'jobs': [_job_payload(j) for j in diff['to_add']],
            'to_add': [_job_payload(j) for j in diff['to_add']],
            'already_on': [
                {
                    **_job_payload(j),
                    'existing_id': j.get('existing_id'),
                    'existing_location': j.get('existing_location') or '',
                }
                for j in diff['already_on']
            ],
            'missing_from_paste': diff['missing_from_paste'],
            'postcode_warnings': diff['postcode_warnings'],
            'invalid': [
                {
                    'jin': j.get('jin') or '',
                    'reference': j.get('reference') or '',
                    'errors': j.get('errors') or [],
                }
                for j in parsed['invalid']
            ],
        }
    )


@login_required
@require_POST
def bulk_add_confirm(request):
    """Create new bulk jobs, optionally remove missing ones, geocode, and plan."""
    planner = active_user(request)
    body = _json_body(request)
    items = body.get('jobs')
    if items is None:
        items = []
    if not isinstance(items, list):
        return JsonResponse({'ok': False, 'error': 'Invalid jobs list.'}, status=400)

    remove_ids_raw = body.get('remove_ids') or []
    if not isinstance(remove_ids_raw, list):
        remove_ids_raw = []
    remove_ids: list[int] = []
    for rid in remove_ids_raw:
        try:
            remove_ids.append(int(rid))
        except (TypeError, ValueError):
            continue

    if not items and not remove_ids:
        return JsonResponse(
            {'ok': False, 'error': 'Nothing to add or remove.'},
            status=400,
        )

    removed = 0
    day = planner_today()
    if remove_ids:
        qs = Job.objects.filter(
            user=planner,
            job_date=day,
            status=Job.Status.PENDING,
            id__in=remove_ids,
        )
        removed = qs.count()
        qs.delete()

    allowed = {c.value for c in Job.AppointmentType}
    created = 0
    geocode_fail = 0
    postcode_warnings: list[str] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        reference = str(item.get('reference') or '').strip()[:100]
        location = str(item.get('location') or '').strip()[:255]
        if not location:
            continue
        # Skip if this reference is already pending (race / double submit)
        if reference:
            exists = Job.objects.filter(
                user=planner,
                job_date=day,
                status=Job.Status.PENDING,
                reference__iexact=reference,
            ).exists()
            if exists:
                continue

        appt = str(item.get('appointment_type') or '').strip().upper()
        if appt not in allowed:
            appt = parse_time_slot(str(item.get('slot_raw') or appt))
        if appt not in allowed:
            appt = Job.AppointmentType.ALLDAY

        dup_pc, dup_jobs = find_duplicate_postcode_jobs(planner, location)
        if dup_pc and dup_jobs:
            postcode_warnings.append(f'{dup_pc} job already on route.')

        allowed_work = {c.value for c in Job.WorkType}
        work_type = str(item.get('work_type') or '').strip()
        if work_type not in allowed_work:
            work_type = ''

        job = Job(
            user=planner,
            reference=reference,
            location=location,
            appointment_type=appt,
            work_type=work_type,
            job_date=day,
            status=Job.Status.PENDING,
            route_order=None,
        )
        result = geocode_location(job.location)
        if result:
            job.lat = result['lat']
            job.lng = result['lng']
            job.geocode_display = result['display'][:255]
        else:
            geocode_fail += 1
        job.save()
        created += 1

    if not created and not removed:
        return JsonResponse(
            {
                'ok': False,
                'error': 'No changes made — jobs may already be on the route.',
            },
            status=400,
        )

    DayRoute.objects.filter(user=planner, job_date=day).update(order_locked=False)
    Job.objects.filter(
        user=planner, job_date=day, status=Job.Status.PENDING
    ).update(
        route_order=None,
        estimated_arrival=None,
        leg_miles_from_previous=None,
        leg_minutes_from_previous=None,
    )
    DayRoute.objects.filter(user=planner, job_date=day).delete()
    plan = plan_current_route(planner, unlock=True)

    raw = str(body.get('raw') or '')
    _save_bulk_paste_log(
        request=request,
        planner=planner,
        day=day,
        raw=raw,
        items=items,
        jobs_added=created,
        jobs_removed=removed,
    )

    log_audit(
        request,
        AuditLog.Action.BULK_ADD,
        message=(
            f'Bulk add: +{created} job{"s" if created != 1 else ""}'
            + (f', −{removed} removed' if removed else '')
        ),
        subject=planner,
        details={
            'jobs_added': created,
            'jobs_removed': removed,
            'job_date': str(day),
            'geocode_fail': geocode_fail,
        },
    )

    parts = []
    if created:
        parts.append(f'Added {created} job{"s" if created != 1 else ""}')
    if removed:
        parts.append(f'removed {removed}')
    msg = ' and '.join(parts) if parts else 'Route updated'
    if plan.job_count:
        msg += (
            f'; planned {plan.job_count} stops'
            f' ({plan.total_miles} mi'
        )
        if plan.total_minutes:
            msg += f', {plan.total_minutes} min'
        msg += ').'
    else:
        msg += '.'
    if geocode_fail:
        msg += f' {geocode_fail} could not be geocoded — check addresses.'
    messages.success(request, msg)
    for warn in postcode_warnings:
        messages.warning(request, warn)
    for warning in plan.warnings:
        messages.warning(request, warning)

    return JsonResponse(
        {
            'ok': True,
            'created': created,
            'removed': removed,
            'redirect': '/',
        }
    )

@login_required
@require_POST
def delete_job(request, pk):
    planner = active_user(request)
    job = _user_job(request, pk)
    log_audit(
        request,
        AuditLog.Action.DELETE_JOB,
        message=f'Deleted job {job.geocode_display or job.location}',
        subject=planner,
        job=job,
        details={'reference': job.reference, 'status': job.status},
    )
    job.delete()
    plan_current_route(planner, unlock=False)
    messages.info(request, 'Job removed.')
    return redirect('dashboard')


@login_required
@require_POST
def update_appointment(request, pk):
    planner = active_user(request)
    job = _user_job(request, pk)
    form = AppointmentTypeForm(
        request.POST,
        instance=job,
        prefix=f'appt-{job.pk}',
    )
    if form.is_valid():
        changed = form.has_changed()
        form.save()
        if changed and job.status == Job.Status.PENDING:
            day = job.job_date or planner_today()
            DayRoute.objects.filter(user=planner, job_date=day).update(
                order_locked=False
            )
            messages.success(
                request,
                f'Updated to {job.appointment_short}. Hit Plan best route to re-order.',
            )
            Job.objects.filter(
                user=planner, job_date=day, status=Job.Status.PENDING
            ).update(
                route_order=None,
                estimated_arrival=None,
                leg_miles_from_previous=None,
                leg_minutes_from_previous=None,
            )
            DayRoute.objects.filter(user=planner, job_date=day).delete()
            log_audit(
                request,
                AuditLog.Action.UPDATE_APPOINTMENT,
                message=f'Appointment → {job.appointment_short}',
                subject=planner,
                job=job,
                details={'appointment_type': job.appointment_type},
            )
        else:
            messages.info(request, 'Appointment unchanged.')
    else:
        messages.error(request, 'Could not update appointment type.')
    return redirect('dashboard')


@login_required
@require_POST
def update_notes(request, pk):
    job = _user_job(request, pk)
    form = JobNotesForm(
        request.POST,
        instance=job,
        prefix=f'notes-{job.pk}',
    )
    if form.is_valid():
        form.save()
        log_audit(
            request,
            AuditLog.Action.UPDATE_NOTES,
            message=f'Note updated on {job.geocode_display or job.location}',
            subject=active_user(request),
            job=job,
        )
        messages.success(request, 'Note saved.')
    else:
        messages.error(request, 'Could not save note.')
    return redirect('dashboard')


@login_required
@require_POST
def mark_job(request, pk):
    planner = active_user(request)
    job = _user_job(request, pk)
    action = request.POST.get('action', '')
    if action in ('done', 'complete'):
        set_job_status(job, Job.Status.DONE)
        log_audit(
            request,
            AuditLog.Action.JOB_COMPLETE,
            message=f'Completed {job.geocode_display or job.location}',
            subject=planner,
            job=job,
            details={'reference': job.reference, 'work_type': job.work_type},
        )
        messages.success(
            request, f'Completed: {job.geocode_display or job.location}'
        )
    elif action == 'mpu':
        if not job.allows_mpu:
            messages.error(
                request,
                'MPU is only for repair jobs (SOGEA / OGEA / copper), not installs.',
            )
        else:
            set_job_status(job, Job.Status.MPU)
            log_audit(
                request,
                AuditLog.Action.JOB_MPU,
                message=f'MPU {job.geocode_display or job.location} (£{Job.MPU_RATE:.2f})',
                subject=planner,
                job=job,
                details={
                    'reference': job.reference,
                    'work_type': job.work_type,
                    'rate': str(Job.MPU_RATE),
                },
            )
            messages.success(
                request,
                f'MPU: {job.geocode_display or job.location} — £{Job.MPU_RATE:.2f}',
            )
    elif action == 'fail':
        set_job_status(job, Job.Status.FAILED)
        log_audit(
            request,
            AuditLog.Action.JOB_FAILED,
            message=f'Failed {job.geocode_display or job.location}',
            subject=planner,
            job=job,
            details={'reference': job.reference, 'work_type': job.work_type},
        )
        messages.info(
            request,
            f'Failed: {job.geocode_display or job.location} — £0 on earnings',
        )
    elif action == 'skip':
        set_job_status(job, Job.Status.SKIPPED)
        log_audit(
            request,
            AuditLog.Action.JOB_SKIPPED,
            message=f'Skipped {job.geocode_display or job.location}',
            subject=planner,
            job=job,
        )
        messages.info(request, f'Skipped: {job.geocode_display or job.location}')
    elif action == 'reopen':
        set_job_status(job, Job.Status.PENDING)
        log_audit(
            request,
            AuditLog.Action.JOB_REOPENED,
            message=f'Reopened {job.geocode_display or job.location}',
            subject=planner,
            job=job,
        )
        messages.info(request, 'Job reopened — re-plan if needed.')
    else:
        messages.error(request, 'Unknown action.')
    return redirect('dashboard')


@login_required
@require_POST
def reorder_jobs(request):
    planner = active_user(request)
    raw = request.POST.get('order', '')
    try:
        ids = [int(x) for x in raw.split(',') if x.strip()]
    except ValueError:
        return JsonResponse({'ok': False, 'error': 'bad order'}, status=400)

    if not ids:
        return JsonResponse({'ok': False, 'error': 'empty'}, status=400)

    owned = set(
        Job.objects.filter(user=planner, id__in=ids).values_list('id', flat=True)
    )
    ids = [i for i in ids if i in owned]
    if not ids:
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)

    plan = apply_manual_order(planner, ids)
    log_audit(
        request,
        AuditLog.Action.REORDER,
        message=f'Manual reorder ({len(ids)} stops)',
        subject=planner,
        details={'order': ids, 'job_count': plan.job_count},
    )
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse(
            {
                'ok': True,
                'total_miles': plan.total_miles,
                'total_minutes': plan.total_minutes,
                'count': plan.job_count,
            }
        )
    messages.success(request, 'Manual order saved and route updated.')
    return redirect('dashboard')


@login_required
@require_POST
def unlock_order(request):
    planner = active_user(request)
    DayRoute.objects.filter(user=planner, job_date=planner_today()).update(
        order_locked=False
    )
    log_audit(
        request,
        AuditLog.Action.UNLOCK_ORDER,
        message='Order unlocked',
        subject=planner,
        details={'job_date': str(planner_today())},
    )
    messages.info(request, 'Order unlocked — Plan best route to auto-optimise again.')
    return redirect('dashboard')


@login_required
@require_POST
def plan_route(request):
    planner = active_user(request)
    plan = plan_current_route(planner, unlock=True)
    for warning in plan.warnings:
        messages.warning(request, warning)
    if plan.job_count:
        drive = f'{plan.total_minutes} min' if plan.total_minutes else ''
        log_audit(
            request,
            AuditLog.Action.PLAN_ROUTE,
            message=(
                f'Planned {plan.job_count} stops, {plan.total_miles} mi'
                + (f', {drive}' if drive else '')
            ),
            subject=planner,
            details={
                'job_count': plan.job_count,
                'total_miles': plan.total_miles,
                'total_minutes': plan.total_minutes,
                'job_date': str(planner_today()),
            },
        )
        messages.success(
            request,
            f'Route planned: {plan.job_count} stops, {plan.total_miles} miles'
            + (f', {drive} driving.' if drive else '.'),
        )
    else:
        messages.error(request, 'No pending jobs to plan.')
    return redirect('dashboard')


@login_required
def settings_view(request):
    planner = active_user(request)
    settings = EngineerSettings.for_user(planner)
    if request.method == 'POST':
        form = SettingsForm(request.POST, instance=settings)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.user = planner
            obj.start_lat = None
            obj.start_lng = None
            obj.start_display = ''
            if obj.start_location.strip():
                result = geocode_location(obj.start_location)
                if result:
                    obj.start_lat = result['lat']
                    obj.start_lng = result['lng']
                    obj.start_display = result['display'][:255]
                    messages.success(
                        request,
                        f'Start point set to {obj.start_display}',
                    )
                else:
                    messages.warning(
                        request,
                        'Saved, but could not geocode the start location.',
                    )
            else:
                messages.success(request, 'Settings cleared.')
            obj.save()
            log_audit(
                request,
                AuditLog.Action.SETTINGS_UPDATE,
                message=f'Start point updated: {obj.start_display or obj.start_location or "(cleared)"}',
                subject=planner,
                details={
                    'start_label': obj.start_label,
                    'start_location': obj.start_location,
                    'start_display': obj.start_display,
                },
            )
            return redirect('settings')
    else:
        form = SettingsForm(instance=settings)

    return render(
        request,
        'planner/settings.html',
        {
            'form': form,
            'settings': settings,
            'routing_provider': active_routing_label(),
        },
    )


@login_required
@user_passes_test(_superuser_required)
def bulk_pastes(request):
    """Searchable archive of work-pack pastes."""
    q = (request.GET.get('q') or '').strip()
    pastes = BulkPasteLog.objects.select_related('user', 'created_by')
    if q:
        pastes = pastes.filter(
            Q(raw_text__icontains=q)
            | Q(search_text__icontains=q.lower())
            | Q(user__username__icontains=q)
            | Q(created_by__username__icontains=q)
        )
    pastes = pastes[:200]
    return render(
        request,
        'planner/bulk_pastes.html',
        {
            'pastes': pastes,
            'q': q,
        },
    )


@login_required
@user_passes_test(_superuser_required)
def bulk_paste_detail(request, pk: int):
    paste = get_object_or_404(
        BulkPasteLog.objects.select_related('user', 'created_by'),
        pk=pk,
    )
    return render(
        request,
        'planner/bulk_paste_detail.html',
        {'paste': paste},
    )


@login_required
@user_passes_test(_superuser_required)
def audit_logs(request):
    """Browseable audit trail for all planner actions."""
    q = (request.GET.get('q') or '').strip()
    action = (request.GET.get('action') or '').strip()
    logs = AuditLog.objects.select_related('actor', 'subject')
    if action and action in {c.value for c in AuditLog.Action}:
        logs = logs.filter(action=action)
    if q:
        logs = logs.filter(
            Q(message__icontains=q)
            | Q(job_reference__icontains=q)
            | Q(job_location__icontains=q)
            | Q(actor__username__icontains=q)
            | Q(subject__username__icontains=q)
            | Q(ip_address__icontains=q)
        )
    total = logs.count()
    logs = logs[:300]
    return render(
        request,
        'planner/audit_logs.html',
        {
            'logs': logs,
            'q': q,
            'action': action,
            'action_choices': AuditLog.Action.choices,
            'total': total,
            'shown': min(total, 300),
        },
    )


@login_required
@require_POST
def clear_route(request):
    planner = active_user(request)
    day = planner_today()
    count = Job.objects.filter(user=planner, job_date=day).count()
    clear_current_route(planner, clear_jobs=True)
    log_audit(
        request,
        AuditLog.Action.CLEAR_ROUTE,
        message=f'Cleared route ({count} job(s) removed)',
        subject=planner,
        details={'jobs_removed': count, 'job_date': str(day)},
    )
    messages.info(request, f'Route cleared ({count} job(s) removed).')
    return redirect('dashboard')


def _parse_iso_date(raw: str) -> date | None:
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


@login_required
def jobs_all(request):
    """Browse jobs across days/statuses (all engineers for superusers)."""
    planner = active_user(request)
    q = (request.GET.get('q') or '').strip()
    status = (request.GET.get('status') or '').strip()
    day_from = _parse_iso_date(request.GET.get('from', ''))
    day_to = _parse_iso_date(request.GET.get('to', ''))
    engineer_id = (request.GET.get('engineer') or '').strip()

    jobs = Job.objects.select_related('user').order_by(
        '-job_date', 'status', 'route_order', 'id'
    )

    is_super = request.user.is_superuser
    engineers = []
    selected_engineer = None
    if is_super:
        engineers = list(list_engineers())
        if engineer_id.isdigit():
            selected_engineer = next(
                (u for u in engineers if u.pk == int(engineer_id)), None
            )
            if selected_engineer:
                jobs = jobs.filter(user=selected_engineer)
        # else: all engineers
    else:
        jobs = jobs.filter(user=planner)

    if status and status in {c.value for c in Job.Status}:
        jobs = jobs.filter(status=status)
    if day_from:
        jobs = jobs.filter(job_date__gte=day_from)
    if day_to:
        jobs = jobs.filter(job_date__lte=day_to)
    if q:
        jobs = jobs.filter(
            Q(reference__icontains=q)
            | Q(location__icontains=q)
            | Q(geocode_display__icontains=q)
            | Q(notes__icontains=q)
            | Q(user__username__icontains=q)
        )

    total = jobs.count()
    jobs = list(jobs[:400])

    if is_super:
        counts_qs = Job.objects.all()
        if selected_engineer:
            counts_qs = counts_qs.filter(user=selected_engineer)
    else:
        counts_qs = Job.objects.filter(user=planner)

    counts_raw = {
        row['status']: row['n']
        for row in counts_qs.values('status').annotate(n=Count('id'))
    }
    status_summary = [
        {'value': value, 'label': label, 'count': counts_raw.get(value, 0)}
        for value, label in Job.Status.choices
    ]

    return render(
        request,
        'planner/jobs_all.html',
        {
            'jobs': jobs,
            'q': q,
            'status': status,
            'day_from': day_from,
            'day_to': day_to,
            'status_choices': Job.Status.choices,
            'status_summary': status_summary,
            'is_super': is_super,
            'engineers': engineers,
            'selected_engineer': selected_engineer,
            'engineer_id': str(selected_engineer.pk) if selected_engineer else '',
            'total': total,
            'shown': len(jobs),
        },
    )


@login_required
def earnings_view(request):
    """Weekly / custom-range earnings for the active engineer."""
    planner = active_user(request)
    today = planner_today()

    range_from = _parse_iso_date(request.GET.get('from', ''))
    range_to = _parse_iso_date(request.GET.get('to', ''))
    week_offset = request.GET.get('week')

    mode = 'week'
    if range_from and range_to:
        if range_to < range_from:
            range_from, range_to = range_to, range_from
        start, end = range_from, range_to
        mode = 'range'
        week_start, week_end = week_bounds(today)
        prev_offset = -1
        next_offset = 1
        current_offset = 0
    else:
        try:
            current_offset = int(week_offset) if week_offset not in (None, '') else 0
        except ValueError:
            current_offset = 0
        week_start, week_end = week_bounds(today)
        start = week_start + timedelta(weeks=current_offset)
        end = week_end + timedelta(weeks=current_offset)
        prev_offset = current_offset - 1
        next_offset = current_offset + 1
        range_from = start
        range_to = end

    days = daily_breakdown(planner, start, end)
    totals = summarise_jobs(
        Job.objects.filter(
            user=planner,
            job_date__gte=start,
            job_date__lte=end,
        ).exclude(status=Job.Status.SKIPPED)
    )

    return render(
        request,
        'planner/earnings.html',
        {
            'mode': mode,
            'start': start,
            'end': end,
            'range_from': range_from,
            'range_to': range_to,
            'days': days,
            'totals': totals,
            'prev_offset': prev_offset,
            'next_offset': next_offset,
            'current_offset': current_offset,
            'planner_day_label': format_planner_day(today),
        },
    )


def _van_kit_redirect(filter_key: str = 'todo'):
    if filter_key not in ('todo', 'ordered', 'all'):
        filter_key = 'todo'
    return redirect(f'{reverse("van_kit")}?filter={filter_key}')


def _parse_van_kit_bulk_line(line: str) -> tuple[str, str] | None:
    """Return (code, name) from 'CODE | Name' or 'CODE - Name'."""
    text = (line or '').strip()
    if not text or text.startswith('#'):
        return None
    for sep in ('|', '\t', ' - ', ' – '):
        if sep in text:
            left, right = text.split(sep, 1)
            code = VanKitItem.normalise_code(left)
            name = right.strip()
            if code and name:
                return code, name
            break
    parts = text.split(None, 1)
    if len(parts) == 2:
        code = VanKitItem.normalise_code(parts[0])
        name = parts[1].strip()
        if code and name:
            return code, name
    return None


@login_required
@user_passes_test(_superuser_required)
def van_kit(request):
    filter_key = (request.GET.get('filter') or 'todo').strip().lower()
    if filter_key not in ('todo', 'ordered', 'all'):
        filter_key = 'todo'

    items = VanKitItem.objects.all()
    total = items.count()
    ordered_count = items.filter(ordered=True).count()
    todo_count = total - ordered_count

    if filter_key == 'todo':
        items = items.filter(ordered=False)
    elif filter_key == 'ordered':
        items = items.filter(ordered=True)

    return render(
        request,
        'planner/van_kit.html',
        {
            'items': items,
            'filter_key': filter_key,
            'total_count': total,
            'ordered_count': ordered_count,
            'todo_count': todo_count,
            'scan_form': VanKitScanForm(),
        },
    )


@login_required
@user_passes_test(_superuser_required)
@require_POST
def van_kit_add(request):
    filter_key = request.POST.get('filter') or 'todo'
    form = VanKitItemForm(request.POST)
    if form.is_valid():
        item = form.save()
        messages.success(request, f'Added {item.product_code} — {item.name}.')
    else:
        for err in form.errors.values():
            for msg in err:
                messages.error(request, msg)
    return _van_kit_redirect(filter_key)


@login_required
@user_passes_test(_superuser_required)
@require_POST
def van_kit_bulk_add(request):
    filter_key = request.POST.get('filter') or 'todo'
    form = VanKitBulkForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Could not read the list.')
        return _van_kit_redirect(filter_key)

    added = 0
    skipped = 0
    for line in form.cleaned_data['lines'].splitlines():
        parsed = _parse_van_kit_bulk_line(line)
        if not parsed:
            continue
        code, name = parsed
        if VanKitItem.objects.filter(product_code__iexact=code).exists():
            skipped += 1
            continue
        VanKitItem.objects.create(product_code=code, name=name)
        added += 1

    if added:
        messages.success(
            request,
            f'Added {added} item{"s" if added != 1 else ""}'
            + (f' ({skipped} already listed).' if skipped else '.'),
        )
    elif skipped:
        messages.info(request, f'Nothing new — {skipped} already on the list.')
    else:
        messages.warning(
            request,
            'No items found. Use one per line: CODE | Item name',
        )
    return _van_kit_redirect(filter_key)


@login_required
@user_passes_test(_superuser_required)
@require_POST
def van_kit_scan(request):
    filter_key = request.POST.get('filter') or 'todo'
    form = VanKitScanForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Enter a product code.')
        return _van_kit_redirect(filter_key)

    code = form.cleaned_data['product_code']
    item = VanKitItem.objects.filter(product_code__iexact=code).first()
    if not item:
        # Also try matching without requiring exact stored normalisation
        for candidate in VanKitItem.objects.all().only('id', 'product_code', 'name', 'ordered'):
            if VanKitItem.normalise_code(candidate.product_code) == code:
                item = candidate
                break
    if not item:
        messages.error(request, f'No item with code {code}.')
        return _van_kit_redirect(filter_key)

    if item.ordered:
        messages.info(request, f'{item.product_code} already marked ordered.')
    else:
        item.ordered = True
        item.ordered_at = timezone.now()
        item.save(update_fields=['ordered', 'ordered_at'])
        log_audit(
            request,
            AuditLog.Action.VAN_KIT_SCAN,
            message=f'Van kit ordered: {item.product_code} — {item.name}',
            details={'product_code': item.product_code, 'name': item.name},
        )
        messages.success(request, f'Marked {item.product_code} — {item.name}.')
    return _van_kit_redirect(filter_key)


@login_required
@user_passes_test(_superuser_required)
@require_POST
def van_kit_toggle(request, pk: int):
    filter_key = request.POST.get('filter') or 'todo'
    item = get_object_or_404(VanKitItem, pk=pk)
    item.ordered = not item.ordered
    item.ordered_at = timezone.now() if item.ordered else None
    item.save(update_fields=['ordered', 'ordered_at'])
    state = 'ordered' if item.ordered else 'still to order'
    log_audit(
        request,
        AuditLog.Action.VAN_KIT_TOGGLE,
        message=f'Van kit {item.product_code} → {state}',
        details={
            'product_code': item.product_code,
            'ordered': item.ordered,
        },
    )
    messages.info(request, f'{item.product_code} → {state}.')
    return _van_kit_redirect(filter_key)


@login_required
@user_passes_test(_superuser_required)
@require_POST
def van_kit_delete(request, pk: int):
    filter_key = request.POST.get('filter') or 'todo'
    item = get_object_or_404(VanKitItem, pk=pk)
    label = f'{item.product_code} — {item.name}'
    item.delete()
    messages.info(request, f'Removed {label}.')
    return _van_kit_redirect(filter_key)


@login_required
@user_passes_test(_superuser_required)
@require_POST
def van_kit_reset_ordered(request):
    filter_key = request.POST.get('filter') or 'todo'
    updated = VanKitItem.objects.filter(ordered=True).update(
        ordered=False,
        ordered_at=None,
    )
    log_audit(
        request,
        AuditLog.Action.VAN_KIT_RESET,
        message=f'Cleared ordered mark on {updated} van kit item(s)',
        details={'cleared': updated},
    )
    messages.info(request, f'Cleared ordered mark on {updated} item(s).')
    return _van_kit_redirect(filter_key)
