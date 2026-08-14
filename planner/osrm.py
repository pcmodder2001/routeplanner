"""
Road routing providers.

Priority:
1. Google Maps (traffic-aware) if GOOGLE_MAPS_API_KEY is set
2. OpenRouteService if OPENROUTESERVICE_API_KEY is set
3. Public OSRM demo
4. Haversine fallback
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from typing import Protocol, Sequence

import requests

logger = logging.getLogger(__name__)

OSRM_BASE = "https://router.project-osrm.org"
ORS_BASE = "https://api.openrouteservice.org"
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
    source: str


@dataclass
class RoadPath:
    miles: float
    minutes: float
    geometry: list[list[float]]
    leg_miles: list[float]
    leg_minutes: list[float]
    source: str


def _google_key() -> str:
    return (os.environ.get("GOOGLE_MAPS_API_KEY") or "").strip()


def _ors_key() -> str:
    return (os.environ.get("OPENROUTESERVICE_API_KEY") or "").strip()


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
    return ";".join(f"{p.lng},{p.lat}" for p in points)


def _haversine_matrices(points: Sequence[HasLatLng]) -> RoadMatrices:
    n = len(points)
    miles = [[0.0] * n for _ in range(n)]
    minutes = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = _road_miles(points[i], points[j])
            miles[i][j] = miles[j][i] = d
            minutes[i][j] = minutes[j][i] = (d / FALLBACK_MPH) * 60 if d else 0.0
    return RoadMatrices(miles=miles, minutes=minutes, source="haversine")


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
        source="haversine",
    )


def _google_matrices(points: Sequence[HasLatLng], key: str) -> RoadMatrices | None:
    n = len(points)
    coords = [f"{p.lat},{p.lng}" for p in points]
    try:
        response = requests.get(
            "https://maps.googleapis.com/maps/api/distancematrix/json",
            params={
                "origins": "|".join(coords),
                "destinations": "|".join(coords),
                "mode": "driving",
                "departure_time": "now",
                "traffic_model": "best_guess",
                "units": "imperial",
                "key": key,
            },
            timeout=25,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        logger.exception("Google Distance Matrix request failed")
        return None

    if data.get("status") != "OK":
        logger.warning("Google Distance Matrix status: %s", data.get("status"))
        return None

    miles = [[0.0] * n for _ in range(n)]
    minutes = [[0.0] * n for _ in range(n)]
    rows = data.get("rows") or []
    for i, row in enumerate(rows):
        elements = row.get("elements") or []
        for j, el in enumerate(elements):
            if el.get("status") != "OK":
                approx = _road_miles(points[i], points[j])
                miles[i][j] = approx
                minutes[i][j] = (approx / FALLBACK_MPH) * 60 if approx else 0.0
                continue
            dur = el.get("duration_in_traffic") or el.get("duration") or {}
            dist = el.get("distance") or {}
            miles[i][j] = (dist.get("value") or 0) / METERS_PER_MILE
            minutes[i][j] = (dur.get("value") or 0) / 60.0
    return RoadMatrices(miles=miles, minutes=minutes, source="google")


def _decode_polyline(encoded: str) -> list[list[float]]:
    """Decode a Google encoded polyline into [[lat, lng], ...]."""
    if not encoded:
        return []
    coords: list[list[float]] = []
    index = 0
    lat = 0
    lng = 0
    length = len(encoded)

    while index < length:
        result = 0
        shift = 0
        while True:
            if index >= length:
                return coords
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlat = ~(result >> 1) if result & 1 else (result >> 1)
        lat += dlat

        result = 0
        shift = 0
        while True:
            if index >= length:
                return coords
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlng = ~(result >> 1) if result & 1 else (result >> 1)
        lng += dlng
        coords.append([lat / 1e5, lng / 1e5])

    return coords


def _google_path(points: Sequence[HasLatLng], key: str) -> RoadPath | None:
    if len(points) < 2:
        return RoadPath(
            miles=0.0,
            minutes=0.0,
            geometry=[[p.lat, p.lng] for p in points],
            leg_miles=[],
            leg_minutes=[],
            source="google",
        )

    params = {
        "origin": f"{points[0].lat},{points[0].lng}",
        "destination": f"{points[-1].lat},{points[-1].lng}",
        "mode": "driving",
        "departure_time": "now",
        "traffic_model": "best_guess",
        "units": "imperial",
        "key": key,
    }
    if len(points) > 2:
        params["waypoints"] = "|".join(f"{p.lat},{p.lng}" for p in points[1:-1])

    try:
        response = requests.get(
            "https://maps.googleapis.com/maps/api/directions/json",
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        logger.exception("Google Directions request failed")
        return None

    if data.get("status") != "OK" or not data.get("routes"):
        logger.warning("Google Directions status: %s", data.get("status"))
        return None

    route = data["routes"][0]
    legs = route.get("legs") or []
    leg_miles: list[float] = []
    leg_minutes: list[float] = []
    geometry: list[list[float]] = []

    for leg in legs:
        dist = (leg.get("distance") or {}).get("value") or 0
        dur = leg.get("duration_in_traffic") or leg.get("duration") or {}
        leg_miles.append(dist / METERS_PER_MILE)
        leg_minutes.append((dur.get("value") or 0) / 60.0)
        # Prefer per-step polylines so the map follows the road network
        for step in leg.get("steps") or []:
            step_poly = ((step.get("polyline") or {}).get("points")) or ""
            decoded = _decode_polyline(step_poly)
            if decoded:
                if geometry and decoded and geometry[-1] == decoded[0]:
                    geometry.extend(decoded[1:])
                else:
                    geometry.extend(decoded)
                continue
            start = step.get("start_location") or {}
            end = step.get("end_location") or {}
            if start.get("lat") is not None:
                geometry.append([start["lat"], start["lng"]])
            if end.get("lat") is not None:
                geometry.append([end["lat"], end["lng"]])

    # Fallback: whole-route overview polyline
    if len(geometry) < 3:
        overview = ((route.get("overview_polyline") or {}).get("points")) or ""
        geometry = _decode_polyline(overview)

    if not geometry:
        geometry = [[p.lat, p.lng] for p in points]

    while len(leg_miles) < len(points) - 1:
        i = len(leg_miles)
        approx = _road_miles(points[i], points[i + 1])
        leg_miles.append(approx)
        leg_minutes.append((approx / FALLBACK_MPH) * 60 if approx else 0.0)

    return RoadPath(
        miles=sum(leg_miles),
        minutes=sum(leg_minutes),
        geometry=geometry,
        leg_miles=leg_miles,
        leg_minutes=leg_minutes,
        source="google",
    )


def _ors_matrices(points: Sequence[HasLatLng], key: str) -> RoadMatrices | None:
    n = len(points)
    locations = [[p.lng, p.lat] for p in points]
    try:
        response = requests.post(
            f"{ORS_BASE}/v2/matrix/driving-car",
            json={"locations": locations, "metrics": ["distance", "duration"], "units": "m"},
            headers={"Authorization": key, "Content-Type": "application/json"},
            timeout=25,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        logger.exception("ORS matrix request failed")
        return None

    distances = data.get("distances") or []
    durations = data.get("durations") or []
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
    return RoadMatrices(miles=miles, minutes=minutes, source="ors")


def _ors_path(points: Sequence[HasLatLng], key: str) -> RoadPath | None:
    if len(points) < 2:
        return RoadPath(
            miles=0.0,
            minutes=0.0,
            geometry=[[p.lat, p.lng] for p in points],
            leg_miles=[],
            leg_minutes=[],
            source="ors",
        )

    try:
        response = requests.post(
            f"{ORS_BASE}/v2/directions/driving-car/geojson",
            json={"coordinates": [[p.lng, p.lat] for p in points]},
            headers={"Authorization": key, "Content-Type": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        logger.exception("ORS directions request failed")
        return None

    features = data.get("features") or []
    if not features:
        return None

    feature = features[0]
    props = feature.get("properties") or {}
    summary = props.get("summary") or {}
    segments = props.get("segments") or []
    geom = (feature.get("geometry") or {}).get("coordinates") or []
    geometry = [[lat, lon] for lon, lat in geom]

    leg_miles = [(seg.get("distance") or 0) / METERS_PER_MILE for seg in segments]
    leg_minutes = [(seg.get("duration") or 0) / 60.0 for seg in segments]

    while len(leg_miles) < len(points) - 1:
        i = len(leg_miles)
        approx = _road_miles(points[i], points[i + 1])
        leg_miles.append(approx)
        leg_minutes.append((approx / FALLBACK_MPH) * 60 if approx else 0.0)

    return RoadPath(
        miles=(summary.get("distance") or 0) / METERS_PER_MILE or sum(leg_miles),
        minutes=(summary.get("duration") or 0) / 60.0 or sum(leg_minutes),
        geometry=geometry or [[p.lat, p.lng] for p in points],
        leg_miles=leg_miles,
        leg_minutes=leg_minutes,
        source="ors",
    )


def _osrm_matrices(points: Sequence[HasLatLng]) -> RoadMatrices | None:
    n = len(points)
    try:
        response = requests.get(
            f"{OSRM_BASE}/table/v1/driving/{_coords_param(points)}",
            params={"annotations": "distance,duration"},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return None

    if data.get("code") != "Ok":
        return None

    distances = data.get("distances") or []
    durations = data.get("durations") or []
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
    return RoadMatrices(miles=miles, minutes=minutes, source="osrm")


def _osrm_path(points: Sequence[HasLatLng]) -> RoadPath | None:
    try:
        response = requests.get(
            f"{OSRM_BASE}/route/v1/driving/{_coords_param(points)}",
            params={"overview": "full", "geometries": "geojson", "steps": "false"},
            timeout=25,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return None

    if data.get("code") != "Ok" or not data.get("routes"):
        return None

    route = data["routes"][0]
    coords = route.get("geometry", {}).get("coordinates") or []
    geometry = [[lat, lon] for lon, lat in coords]
    leg_miles = [(leg.get("distance") or 0) / METERS_PER_MILE for leg in route.get("legs") or []]
    leg_minutes = [(leg.get("duration") or 0) / 60.0 for leg in route.get("legs") or []]

    while len(leg_miles) < len(points) - 1:
        i = len(leg_miles)
        approx = _road_miles(points[i], points[i + 1])
        leg_miles.append(approx)
        leg_minutes.append((approx / FALLBACK_MPH) * 60 if approx else 0.0)

    return RoadPath(
        miles=(route.get("distance") or 0) / METERS_PER_MILE,
        minutes=(route.get("duration") or 0) / 60.0,
        geometry=geometry or [[p.lat, p.lng] for p in points],
        leg_miles=leg_miles,
        leg_minutes=leg_minutes,
        source="osrm",
    )


def fetch_road_matrices(points: Sequence[HasLatLng]) -> RoadMatrices:
    n = len(points)
    if n == 0:
        return RoadMatrices(miles=[], minutes=[], source="osrm")
    if n == 1:
        return RoadMatrices(miles=[[0.0]], minutes=[[0.0]], source="osrm")

    google = _google_key()
    if google:
        result = _google_matrices(points, google)
        if result:
            return result

    ors = _ors_key()
    if ors:
        result = _ors_matrices(points, ors)
        if result:
            return result

    result = _osrm_matrices(points)
    if result:
        return result
    return _haversine_matrices(points)


def fetch_road_path(points: Sequence[HasLatLng]) -> RoadPath:
    if len(points) < 2:
        return RoadPath(
            miles=0.0,
            minutes=0.0,
            geometry=[[p.lat, p.lng] for p in points],
            leg_miles=[],
            leg_minutes=[],
            source="osrm",
        )

    google = _google_key()
    if google:
        result = _google_path(points, google)
        if result:
            return result

    ors = _ors_key()
    if ors:
        result = _ors_path(points, ors)
        if result:
            return result

    result = _osrm_path(points)
    if result:
        return result
    return _fallback_path(points)


def active_routing_label() -> str:
    if _google_key():
        return "google"
    if _ors_key():
        return "ors"
    return "osrm"
