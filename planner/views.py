from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import AppointmentTypeForm, JobForm, JobNotesForm, SettingsForm
from .geocoding import geocode_location
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


def dashboard(request):
    jobs = Job.objects.all().order_by(
        'status',
        'route_order',
        'appointment_type',
        'id',
    )
    # Pending with order first, then unordered pending, then done/skipped
    pending = [j for j in jobs if j.status == Job.Status.PENDING]
    pending_ordered = sorted(
        [j for j in pending if j.route_order is not None],
        key=lambda j: j.route_order or 0,
    )
    pending_rest = [j for j in pending if j.route_order is None]
    finished = [j for j in jobs if j.status != Job.Status.PENDING]
    display_jobs = pending_ordered + pending_rest + finished

    settings = EngineerSettings.get_solo()
    planned = pending_ordered
    day_route = DayRoute.objects.order_by('-updated_at').first()
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
            }
        )
    for job in planned:
        if job.is_geocoded:
            map_points.append(
                {
                    'order': job.route_order,
                    'label': job.geocode_display
                    or job.reference
                    or job.location,
                    'lat': job.lat,
                    'lng': job.lng,
                    'type': job.appointment_type,
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
    for job in planned:
        if job.is_geocoded:
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
    next_job, next_nav_url = next_job_navigate_url()
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
    }
    return render(request, 'planner/dashboard.html', context)


@require_POST
def add_job(request):
    form = JobForm(request.POST)
    if form.is_valid():
        job = form.save(commit=False)
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
        job.status = Job.Status.PENDING
        job.route_order = None
        job.save()
        # Invalidate auto order but keep done/skipped jobs
        DayRoute.objects.all().update(order_locked=False)
        Job.objects.filter(status=Job.Status.PENDING).update(
            route_order=None,
            estimated_arrival=None,
            leg_miles_from_previous=None,
            leg_minutes_from_previous=None,
        )
        DayRoute.objects.all().delete()
        return redirect('dashboard')

    messages.error(request, 'Could not add job — check the form.')
    return redirect('dashboard')


@require_POST
def delete_job(request, pk):
    job = get_object_or_404(Job, pk=pk)
    job.delete()
    plan_current_route(unlock=False)
    messages.info(request, 'Job removed.')
    return redirect('dashboard')


@require_POST
def update_appointment(request, pk):
    job = get_object_or_404(Job, pk=pk)
    form = AppointmentTypeForm(
        request.POST,
        instance=job,
        prefix=f'appt-{job.pk}',
    )
    if form.is_valid():
        changed = form.has_changed()
        form.save()
        if changed and job.status == Job.Status.PENDING:
            DayRoute.objects.all().update(order_locked=False)
            messages.success(
                request,
                f'Updated to {job.appointment_short}. Hit Plan best route to re-order.',
            )
            Job.objects.filter(status=Job.Status.PENDING).update(
                route_order=None,
                estimated_arrival=None,
                leg_miles_from_previous=None,
                leg_minutes_from_previous=None,
            )
            DayRoute.objects.all().delete()
        else:
            messages.info(request, 'Appointment unchanged.')
    else:
        messages.error(request, 'Could not update appointment type.')
    return redirect('dashboard')


@require_POST
def update_notes(request, pk):
    job = get_object_or_404(Job, pk=pk)
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


@require_POST
def mark_job(request, pk):
    job = get_object_or_404(Job, pk=pk)
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


@require_POST
def reorder_jobs(request):
    raw = request.POST.get('order', '')
    try:
        ids = [int(x) for x in raw.split(',') if x.strip()]
    except ValueError:
        return JsonResponse({'ok': False, 'error': 'bad order'}, status=400)

    if not ids:
        return JsonResponse({'ok': False, 'error': 'empty'}, status=400)

    plan = apply_manual_order(ids)
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


@require_POST
def unlock_order(request):
    DayRoute.objects.all().update(order_locked=False)
    messages.info(request, 'Order unlocked — Plan best route to auto-optimise again.')
    return redirect('dashboard')


@require_POST
def plan_route(request):
    plan = plan_current_route(unlock=True)
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


def settings_view(request):
    settings = EngineerSettings.get_solo()
    if request.method == 'POST':
        form = SettingsForm(request.POST, instance=settings)
        if form.is_valid():
            obj = form.save(commit=False)
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


@require_POST
def clear_route(request):
    count = Job.objects.count()
    clear_current_route(clear_jobs=True)
    messages.info(request, f'Route cleared ({count} job(s) removed).')
    return redirect('dashboard')
