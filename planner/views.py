import json

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .acting import (
    active_user,
    clear_view_as,
    list_engineers,
    set_view_as,
)
from .bulk_parse import (
    diff_bulk_against_route,
    extract_uk_postcode,
    find_duplicate_postcode_jobs,
    job_postcode,
    parse_bulk_jobs,
    parse_time_slot,
)
from .forms import (
    AppointmentTypeForm,
    JobForm,
    JobNotesForm,
    LoginForm,
    RegisterForm,
    SettingsForm,
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
from .models import DayRoute, EngineerSettings, Job
from .osrm import active_routing_label
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
            messages.error(request, 'Invalid username or password.')
        elif not user.is_active:
            messages.error(request, 'This account is disabled.')
        else:
            login(request, user)
            clear_view_as(request)
            if form.cleaned_data.get('remember_me'):
                request.session.set_expiry(REMEMBER_ME_SECONDS)
            else:
                request.session.set_expiry(0)  # until browser closes
            EngineerSettings.for_user(user)
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
        messages.success(request, f'Welcome, {user.username} — account created.')
        return redirect('dashboard')

    return render(request, 'planner/register.html', {'form': form})


@require_POST
def logout_view(request):
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
        messages.info(request, f'Viewing as {other.username}.')
    return redirect('dashboard')


@login_required
@user_passes_test(_superuser_required)
@require_POST
def stop_view_as(request):
    clear_view_as(request)
    messages.info(request, 'Back to your own account.')
    return redirect('dashboard')


@login_required
def dashboard(request):
    planner = active_user(request)
    jobs = Job.objects.filter(user=planner).order_by(
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
    day_route = (
        DayRoute.objects.filter(user=planner).order_by('-updated_at').first()
    )
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
        job.save()
        DayRoute.objects.filter(user=planner).update(order_locked=False)
        Job.objects.filter(user=planner, status=Job.Status.PENDING).update(
            route_order=None,
            estimated_arrival=None,
            leg_miles_from_previous=None,
            leg_minutes_from_previous=None,
        )
        DayRoute.objects.filter(user=planner).delete()
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
    }


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
    if remove_ids:
        qs = Job.objects.filter(
            user=planner,
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

        job = Job(
            user=planner,
            reference=reference,
            location=location,
            appointment_type=appt,
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

    DayRoute.objects.filter(user=planner).update(order_locked=False)
    Job.objects.filter(user=planner, status=Job.Status.PENDING).update(
        route_order=None,
        estimated_arrival=None,
        leg_miles_from_previous=None,
        leg_minutes_from_previous=None,
    )
    DayRoute.objects.filter(user=planner).delete()
    plan = plan_current_route(planner, unlock=True)

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
            DayRoute.objects.filter(user=planner).update(order_locked=False)
            messages.success(
                request,
                f'Updated to {job.appointment_short}. Hit Plan best route to re-order.',
            )
            Job.objects.filter(user=planner, status=Job.Status.PENDING).update(
                route_order=None,
                estimated_arrival=None,
                leg_miles_from_previous=None,
                leg_minutes_from_previous=None,
            )
            DayRoute.objects.filter(user=planner).delete()
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
        messages.success(request, 'Note saved.')
    else:
        messages.error(request, 'Could not save note.')
    return redirect('dashboard')


@login_required
@require_POST
def mark_job(request, pk):
    job = _user_job(request, pk)
    action = request.POST.get('action', '')
    if action == 'done':
        set_job_status(job, Job.Status.DONE)
        messages.success(request, f'Marked done: {job.geocode_display or job.location}')
    elif action == 'skip':
        set_job_status(job, Job.Status.SKIPPED)
        messages.info(request, f'Skipped: {job.geocode_display or job.location}')
    elif action == 'reopen':
        set_job_status(job, Job.Status.PENDING)
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
    DayRoute.objects.filter(user=planner).update(order_locked=False)
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
@require_POST
def clear_route(request):
    planner = active_user(request)
    count = Job.objects.filter(user=planner).count()
    clear_current_route(planner, clear_jobs=True)
    messages.info(request, f'Route cleared ({count} job(s) removed).')
    return redirect('dashboard')
