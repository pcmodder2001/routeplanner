"""Road routing via the public OSRM demo server (OpenStreetMap)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, Sequence

import requests

OSRM_BASE = 'https://router.project-osrm.org'
METERS_PER_MILE = 1609.344
EARTH_RADIUS_MILES = 3958.8
ROAD_FACTOR = 1.35
FALLBACK_MPH = 22.0


class HasLatLng(Protocol):
    lat: float
    lng: float


@dataclass
class RoadMatrices:
    miles: list[list[float]]
    minutes: list[list[float]]
    source: str  # 'osrm' | 'haversine'


@dataclass
class RoadPath:
    miles: float
    minutes: float
    geometry: list[list[float]]  # [[lat, lng], ...]
    leg_miles: list[float]
    leg_minutes: list[float]
    source: str


def _haversine_miles(a: HasLatLng, b: HasLatLng) -> float:
    lat1, lon1 = math.radians(a.lat), math.radians(a.lng)
    lat2, lon2 = math.radians(b.lat), math.radians(b.lng)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(h))


def _road_miles(a: HasLatLng, b: HasLatLng) -> float:
    return _haversine_miles(a, b) * ROAD_FACTOR


def _coords_param(points: Sequence[HasLatLng]) -> str:
    return ';'.join(f'{p.lng},{p.lat}' for p in points)


def fetch_road_matrices(points: Sequence[HasLatLng]) -> RoadMatrices:
    """Distance + duration matrix between all points (driving)."""
    n = len(points)
    if n == 0:
        return RoadMatrices(miles=[], minutes=[], source='osrm')
    if n == 1:
        return RoadMatrices(miles=[[0.0]], minutes=[[0.0]], source='osrm')

    url = f'{OSRM_BASE}/table/v1/driving/{_coords_param(points)}'
    try:
        response = requests.get(
            url,
            params={'annotations': 'distance,duration'},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return _haversine_matrices(points)

    if data.get('code') != 'Ok':
        return _haversine_matrices(points)

    distances = data.get('distances') or []
    durations = data.get('durations') or []
    miles = [[0.0] * n for _ in range(n)]
    minutes = [[0.0] * n for _ in range(n)]

    for i in range(n):
        for j in range(n):
            d = distances[i][j] if i < len(distances) and j < len(distances[i]) else None
            t = durations[i][j] if i < len(durations) and j < len(durations[i]) else None
            if d is None or t is None:
                approx = _road_miles(points[i], points[j])
                miles[i][j] = approx
                minutes[i][j] = (approx / FALLBACK_MPH) * 60 if approx else 0.0
            else:
                miles[i][j] = d / METERS_PER_MILE
                minutes[i][j] = t / 60.0

    return RoadMatrices(miles=miles, minutes=minutes, source='osrm')


def _haversine_matrices(points: Sequence[HasLatLng]) -> RoadMatrices:
    n = len(points)
    miles = [[0.0] * n for _ in range(n)]
    minutes = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = _road_miles(points[i], points[j])
            miles[i][j] = miles[j][i] = d
            minutes[i][j] = minutes[j][i] = (d / FALLBACK_MPH) * 60 if d else 0.0
    return RoadMatrices(miles=miles, minutes=minutes, source='haversine')


def fetch_road_path(points: Sequence[HasLatLng]) -> RoadPath:
    """Full driving route along roads for an ordered list of stops."""
    if len(points) < 2:
        return RoadPath(
            miles=0.0,
            minutes=0.0,
            geometry=[[p.lat, p.lng] for p in points],
            leg_miles=[],
            leg_minutes=[],
            source='osrm',
        )

    url = f'{OSRM_BASE}/route/v1/driving/{_coords_param(points)}'
    try:
        response = requests.get(
            url,
            params={
                'overview': 'full',
                'geometries': 'geojson',
                'steps': 'false',
            },
            timeout=25,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return _fallback_path(points)

    if data.get('code') != 'Ok' or not data.get('routes'):
        return _fallback_path(points)

    route = data['routes'][0]
    coords = route.get('geometry', {}).get('coordinates') or []
    geometry = [[lat, lon] for lon, lat in coords]

    leg_miles: list[float] = []
    leg_minutes: list[float] = []
    for leg in route.get('legs') or []:
        leg_miles.append((leg.get('distance') or 0) / METERS_PER_MILE)
        leg_minutes.append((leg.get('duration') or 0) / 60.0)

    while len(leg_miles) < len(points) - 1:
        i = len(leg_miles)
        approx = _road_miles(points[i], points[i + 1])
        leg_miles.append(approx)
        leg_minutes.append((approx / FALLBACK_MPH) * 60 if approx else 0.0)

    return RoadPath(
        miles=(route.get('distance') or 0) / METERS_PER_MILE,
        minutes=(route.get('duration') or 0) / 60.0,
        geometry=geometry or [[p.lat, p.lng] for p in points],
        leg_miles=leg_miles,
        leg_minutes=leg_minutes,
        source='osrm',
    )


def _fallback_path(points: Sequence[HasLatLng]) -> RoadPath:
    geometry = [[p.lat, p.lng] for p in points]
    leg_miles = []
    leg_minutes = []
    for i in range(len(points) - 1):
        d = _road_miles(points[i], points[i + 1])
        leg_miles.append(d)
        leg_minutes.append((d / FALLBACK_MPH) * 60 if d else 0.0)
    return RoadPath(
        miles=sum(leg_miles),
        minutes=sum(leg_minutes),
        geometry=geometry,
        leg_miles=leg_miles,
        leg_minutes=leg_minutes,
        source='haversine',
    )
