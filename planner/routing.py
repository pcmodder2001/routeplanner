"""
Constrained route optimiser for Openreach-style appointments.

Rules:
- AM jobs (8am–1pm) come before PM jobs (1pm–6pm)
- All-day jobs can sit wherever they best fit on the route
- With typically 3–10 stops we can solve exactly / near-exactly
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, Sequence

from django.utils import timezone

from .geocoding import geocode_location
from .models import DayRoute, EngineerSettings, Job
from .osrm import fetch_road_matrices, fetch_road_path

EARTH_RADIUS_MILES = 3958.8
# Approximate road factor vs straight-line distance for UK local driving
ROAD_FACTOR = 1.35
AVG_SPEED_MPH = 22.0  # fallback only
STOP_MINUTES = 45  # assumed time on site


@dataclass
class Point:
    key: str
    label: str
    lat: float
    lng: float
    appointment: str | None = None  # AM / PM / ALLDAY / START
    job_id: int | None = None


@dataclass
class PlannedStop:
    order: int
    job: Job | None
    label: str
    appointment: str
    lat: float
    lng: float
    miles_from_previous: float
    minutes_from_previous: int
    estimated_arrival: time | None
    is_start: bool = False


@dataclass
class RoutePlan:
    stops: list[PlannedStop]
    total_miles: float
    total_minutes: int
    job_count: int
    warnings: list[str]
    geometry: list[list[float]]
    source: str


def haversine_miles(a: Point, b: Point) -> float:
    lat1, lon1 = math.radians(a.lat), math.radians(a.lng)
    lat2, lon2 = math.radians(b.lat), math.radians(b.lng)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(h))


def road_miles(a: Point, b: Point) -> float:
    return haversine_miles(a, b) * ROAD_FACTOR


def build_distance_matrix(points: Sequence[Point]) -> list[list[float]]:
    """Fallback straight-line matrix (tests / offline). Prefer OSRM in plan_route."""
    n = len(points)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = road_miles(points[i], points[j])
            matrix[i][j] = d
            matrix[j][i] = d
    return matrix


def path_length(order: Sequence[int], matrix: Sequence[Sequence[float]]) -> float:
    if len(order) < 2:
        return 0.0
    return sum(matrix[order[i]][order[i + 1]] for i in range(len(order) - 1))


def best_permutation(
    indices: Sequence[int],
    matrix: Sequence[Sequence[float]],
    start_idx: int | None = None,
    end_anchor_to: int | None = None,
) -> list[int]:
    """Exact TSP path for small sets. Optional fixed start and/or end."""
    if not indices:
        return []
    if len(indices) == 1:
        return list(indices)

    best: list[int] | None = None
    best_len = float('inf')

    for perm in itertools.permutations(indices):
        route = list(perm)
        full = ([start_idx] if start_idx is not None else []) + route
        if end_anchor_to is not None:
            # not appending end into length? we only care about arriving at jobs
            pass
        length = path_length(full, matrix)
        if length < best_len:
            best_len = length
            best = route

    return best or list(indices)


def nearest_neighbor(
    indices: Sequence[int],
    matrix: Sequence[Sequence[float]],
    start_from: int,
) -> list[int]:
    remaining = set(indices)
    if not remaining:
        return []
    current = min(remaining, key=lambda i: matrix[start_from][i])
    order = [current]
    remaining.remove(current)
    while remaining:
        current = min(remaining, key=lambda i: matrix[current][i])
        order.append(current)
        remaining.remove(current)
    return order


def two_opt(order: list[int], matrix: Sequence[Sequence[float]], start_idx: int) -> list[int]:
    """2-opt improvement on a path starting at start_idx (not in order)."""
    if len(order) < 3:
        return order

    improved = True
    best = order[:]
    while improved:
        improved = False
        for i in range(len(best) - 1):
            for k in range(i + 1, len(best)):
                candidate = best[:i] + best[i : k + 1][::-1] + best[k + 1 :]
                if path_length([start_idx] + candidate, matrix) < path_length(
                    [start_idx] + best, matrix
                ):
                    best = candidate
                    improved = True
        order = best
    return best


def optimise_cluster(
    indices: Sequence[int],
    matrix: Sequence[Sequence[float]],
    start_idx: int,
) -> list[int]:
    if not indices:
        return []
    if len(indices) <= 7:
        return best_permutation(indices, matrix, start_idx=start_idx)
    seed = nearest_neighbor(indices, matrix, start_from=start_idx)
    return two_opt(seed, matrix, start_idx)


def insertion_cost(
    route: Sequence[int],
    job_idx: int,
    position: int,
    matrix: Sequence[Sequence[float]],
    start_idx: int,
) -> float:
    """Extra miles from inserting job_idx at position in route (0..len)."""
    prev = start_idx if position == 0 else route[position - 1]
    if position == len(route):
        return matrix[prev][job_idx]
    nxt = route[position]
    return matrix[prev][job_idx] + matrix[job_idx][nxt] - matrix[prev][nxt]


def best_insert_position(
    route: Sequence[int],
    job_idx: int,
    matrix: Sequence[Sequence[float]],
    start_idx: int,
) -> int:
    best_pos = 0
    best_cost = float('inf')
    for pos in range(len(route) + 1):
        cost = insertion_cost(route, job_idx, pos, matrix, start_idx)
        if cost < best_cost:
            best_cost = cost
            best_pos = pos
    return best_pos


def insert_allday_jobs(
    am_order: list[int],
    pm_order: list[int],
    allday_indices: Sequence[int],
    matrix: Sequence[Sequence[float]],
    start_idx: int,
) -> list[int]:
    """
    Insert each all-day job where it adds the least distance.

    Combined route is AM block then PM block. All-day can land in either.
    """
    route = am_order + pm_order
    am_count = len(am_order)

    # Insert farthest-from-start first so local inserts refine later
    ordered_flex = sorted(
        allday_indices,
        key=lambda i: matrix[start_idx][i],
        reverse=True,
    )

    for job_idx in ordered_flex:
        pos = best_insert_position(route, job_idx, matrix, start_idx)
        route.insert(pos, job_idx)
        if pos <= am_count:
            am_count += 1

    # Light polish: try moving each ALLDAY within the route if cheaper
    flex_set = set(allday_indices)
    improved = True
    while improved:
        improved = False
        for job_idx in list(flex_set):
            if job_idx not in route:
                continue
            current_pos = route.index(job_idx)
            without = route[:current_pos] + route[current_pos + 1 :]
            best_pos = best_insert_position(without, job_idx, matrix, start_idx)
            trial = without[:best_pos] + [job_idx] + without[best_pos:]
            if path_length([start_idx] + trial, matrix) + 1e-9 < path_length(
                [start_idx] + route, matrix
            ):
                route = trial
                improved = True

    # Enforce AM-before-PM for fixed appointment jobs (all-day may sit anywhere)
    return _repair_am_pm_order(route, am_order, pm_order, flex_set, matrix, start_idx)


def _repair_am_pm_order(
    route: list[int],
    am_order: Sequence[int],
    pm_order: Sequence[int],
    flex_set: set[int],
    matrix: Sequence[Sequence[float]],
    start_idx: int,
) -> list[int]:
    """Ensure fixed AM jobs appear before fixed PM jobs; keep relative cluster order."""
    am_set = set(am_order)
    pm_set = set(pm_order)

    fixed_am = [i for i in route if i in am_set]
    fixed_pm = [i for i in route if i in pm_set]
    flex = [i for i in route if i in flex_set]

    # Rebuild: place flex optimally around fixed AM then fixed PM skeleton
    skeleton = list(fixed_am) + list(fixed_pm)
    for job_idx in flex:
        pos = best_insert_position(skeleton, job_idx, matrix, start_idx)
        skeleton.insert(pos, job_idx)

    # Final check: no fixed PM before fixed AM
    seen_pm = False
    for idx in skeleton:
        if idx in pm_set:
            seen_pm = True
        if seen_pm and idx in am_set:
            # Fall back to strict AM block + flex inserted + PM block
            return _strict_blocks(fixed_am, fixed_pm, flex, matrix, start_idx)
    return skeleton


def _strict_blocks(
    am: Sequence[int],
    pm: Sequence[int],
    flex: Sequence[int],
    matrix: Sequence[Sequence[float]],
    start_idx: int,
) -> list[int]:
    route = list(am) + list(pm)
    for job_idx in flex:
        pos = best_insert_position(route, job_idx, matrix, start_idx)
        route.insert(pos, job_idx)
    return route


def estimate_arrivals(
    drive_minutes: Sequence[float],
    appointment_types: Sequence[str],
    start_time: time = time(8, 0),
) -> list[time]:
    """
    Build ETAs from real drive minutes. PM appointments are not shown before 13:00
    (engineer waits / pads until the PM window if they arrive early).
    """
    arrivals: list[time] = []
    clock = datetime.combine(date.today(), start_time)
    pm_open = datetime.combine(date.today(), time(13, 0))

    for i, mins in enumerate(drive_minutes):
        if i == 0:
            clock += timedelta(minutes=mins)
        else:
            clock += timedelta(minutes=STOP_MINUTES)
            clock += timedelta(minutes=mins)

        appt = appointment_types[i]
        if appt == Job.AppointmentType.PM and clock < pm_open:
            clock = pm_open

        arrivals.append(clock.time().replace(second=0, microsecond=0))
    return arrivals


def clear_current_route(*, clear_jobs: bool = False) -> None:
    """Reset planned order/geometry. Optionally wipe all jobs (evening clear)."""
    if clear_jobs:
        Job.objects.all().delete()
    else:
        Job.objects.all().update(
            route_order=None,
            estimated_arrival=None,
            leg_miles_from_previous=None,
            leg_minutes_from_previous=None,
        )
    DayRoute.objects.all().delete()


def ensure_geocoded(jobs: Iterable[Job]) -> list[str]:
    """Resolve coords + street names. Refresh postcode jobs so labels stay accurate."""
    from .geocoding import looks_like_postcode

    warnings: list[str] = []
    for job in jobs:
        needs_lookup = (not job.is_geocoded) or looks_like_postcode(job.location)
        if not needs_lookup:
            continue
        result = geocode_location(job.location)
        if not result:
            if not job.is_geocoded:
                warnings.append(f'Could not locate: {job.location}')
            continue
        job.lat = result['lat']
        job.lng = result['lng']
        job.geocode_display = result['display'][:255]
        job.save(update_fields=['lat', 'lng', 'geocode_display'])
    return warnings


def ensure_start_geocoded(settings: EngineerSettings) -> str | None:
    if not settings.start_location.strip():
        return 'Set a start postcode/address in Settings so the route knows where you begin.'
    needs_refresh = (
        settings.start_lat is None
        or settings.start_lng is None
        or not settings.start_display
    )
    if not needs_refresh:
        return None
    result = geocode_location(settings.start_location)
    if not result:
        return f'Could not locate start: {settings.start_location}'
    settings.start_lat = result['lat']
    settings.start_lng = result['lng']
    settings.start_display = result['display'][:255]
    settings.save(update_fields=['start_lat', 'start_lng', 'start_display'])
    return None


def plan_current_route() -> RoutePlan:
    """Plan the best route for all jobs currently in the list."""
    settings = EngineerSettings.get_solo()
    warnings: list[str] = []
    route_date = timezone.localdate()

    start_warning = ensure_start_geocoded(settings)
    if start_warning:
        warnings.append(start_warning)

    jobs = list(Job.objects.all())
    warnings.extend(ensure_geocoded(jobs))

    geocoded = [j for j in jobs if j.is_geocoded]
    if not geocoded:
        clear_current_route(clear_jobs=False)
        return RoutePlan(
            stops=[],
            total_miles=0.0,
            total_minutes=0,
            job_count=0,
            warnings=warnings,
            geometry=[],
            source='',
        )

    # Default start: centroid of jobs if no depot
    if settings.start_lat is None or settings.start_lng is None:
        start = Point(
            key='start',
            label='Start (auto)',
            lat=sum(j.lat for j in geocoded) / len(geocoded),
            lng=sum(j.lng for j in geocoded) / len(geocoded),
            appointment='START',
        )
    else:
        start = Point(
            key='start',
            label=settings.start_display
            or settings.start_label
            or settings.start_location,
            lat=settings.start_lat,
            lng=settings.start_lng,
            appointment='START',
        )

    points: list[Point] = [start]
    for job in geocoded:
        points.append(
            Point(
                key=f'job-{job.pk}',
                label=job.reference or job.location,
                lat=job.lat,
                lng=job.lng,
                appointment=job.appointment_type,
                job_id=job.pk,
            )
        )

    road_matrix = fetch_road_matrices(points)
    matrix = road_matrix.miles
    if road_matrix.source != 'osrm':
        warnings.append(
            'Live road routing unavailable — used approximate distances for ordering.'
        )

    start_idx = 0
    index_by_job = {p.job_id: i for i, p in enumerate(points) if p.job_id}

    am_indices = [
        index_by_job[j.pk]
        for j in geocoded
        if j.appointment_type == Job.AppointmentType.AM
    ]
    pm_indices = [
        index_by_job[j.pk]
        for j in geocoded
        if j.appointment_type == Job.AppointmentType.PM
    ]
    allday_indices = [
        index_by_job[j.pk]
        for j in geocoded
        if j.appointment_type == Job.AppointmentType.ALLDAY
    ]

    am_order = optimise_cluster(am_indices, matrix, start_idx)
    pm_start = am_order[-1] if am_order else start_idx
    pm_order = optimise_cluster(pm_indices, matrix, pm_start)

    final_order = insert_allday_jobs(
        am_order, pm_order, allday_indices, matrix, start_idx
    )

    ordered_points = [points[start_idx]] + [points[i] for i in final_order]
    road_path = fetch_road_path(ordered_points)
    if road_path.source != 'osrm':
        warnings.append(
            'Could not fetch full road path — map may show straight lines between stops.'
        )

    clear_current_route(clear_jobs=False)

    job_by_id = {j.pk: j for j in geocoded}
    ordered_jobs: list[Job] = []
    miles_legs = road_path.leg_miles
    minutes_legs = road_path.leg_minutes

    for seq, point_idx in enumerate(final_order, start=1):
        point = points[point_idx]
        job = job_by_id[point.job_id]
        leg_i = seq - 1
        miles = miles_legs[leg_i] if leg_i < len(miles_legs) else matrix[0][point_idx]
        mins = minutes_legs[leg_i] if leg_i < len(minutes_legs) else 0.0
        job.route_order = seq
        job.leg_miles_from_previous = round(miles, 2)
        job.leg_minutes_from_previous = max(0, int(round(mins)))
        ordered_jobs.append(job)

    arrivals = estimate_arrivals(
        minutes_legs[: len(ordered_jobs)],
        [job.appointment_type for job in ordered_jobs],
    )
    for job, arrival in zip(ordered_jobs, arrivals):
        job.estimated_arrival = arrival
        job.save(
            update_fields=[
                'route_order',
                'leg_miles_from_previous',
                'leg_minutes_from_previous',
                'estimated_arrival',
            ]
        )

    total_miles = round(road_path.miles, 1)
    total_minutes = max(0, int(round(road_path.minutes)))

    DayRoute.objects.update_or_create(
        job_date=route_date,
        defaults={
            'geometry': road_path.geometry,
            'total_miles': total_miles,
            'total_minutes': total_minutes,
            'source': road_path.source,
        },
    )

    stops: list[PlannedStop] = [
        PlannedStop(
            order=0,
            job=None,
            label=start.label,
            appointment='START',
            lat=start.lat,
            lng=start.lng,
            miles_from_previous=0.0,
            minutes_from_previous=0,
            estimated_arrival=time(8, 0),
            is_start=True,
        )
    ]
    for job in ordered_jobs:
        stops.append(
            PlannedStop(
                order=job.route_order or 0,
                job=job,
                label=job.reference or job.location,
                appointment=job.appointment_type,
                lat=job.lat,
                lng=job.lng,
                miles_from_previous=job.leg_miles_from_previous or 0.0,
                minutes_from_previous=job.leg_minutes_from_previous or 0,
                estimated_arrival=job.estimated_arrival,
            )
        )

    for job in ordered_jobs:
        if (
            job.appointment_type == Job.AppointmentType.AM
            and job.estimated_arrival
            and job.estimated_arrival > time(13, 0)
        ):
            warnings.append(
                f'AM job "{job.location}" estimated after 1pm — day may be overloaded.'
            )

    ungeocoded = [j for j in jobs if not j.is_geocoded]
    if ungeocoded:
        warnings.append(
            f'{len(ungeocoded)} job(s) skipped because they could not be located.'
        )

    return RoutePlan(
        stops=stops,
        total_miles=total_miles,
        total_minutes=total_minutes,
        job_count=len(ordered_jobs),
        warnings=warnings,
        geometry=road_path.geometry,
        source=road_path.source,
    )


def google_maps_url(stops: Sequence[PlannedStop]) -> str:
    """Build a Google Maps multi-stop directions link."""
    coords = [s for s in stops if s.lat is not None and s.lng is not None]
    if len(coords) < 2:
        return ''
    parts = [f'{s.lat},{s.lng}' for s in coords]
    origin = parts[0]
    destination = parts[-1]
    waypoints = parts[1:-1]
    url = (
        'https://www.google.com/maps/dir/?api=1'
        f'&origin={origin}&destination={destination}&travelmode=driving'
    )
    if waypoints:
        url += '&waypoints=' + '%7C'.join(waypoints)
    return url
