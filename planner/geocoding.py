"""UK-friendly geocoding via postcodes.io and Nominatim."""

from __future__ import annotations

import re
import time
from typing import Any

import requests

# Matches spaced or compact UK postcodes, e.g. HD9 1UY / hd91uy / SW1A1AA
UK_POSTCODE_RE = re.compile(
    r'^([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})$',
    re.IGNORECASE,
)
UK_POSTCODE_FIND_RE = re.compile(
    r'\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b',
    re.IGNORECASE,
)

USER_AGENT = 'OpenreachRoutePlanner/1.0 (local engineer tool)'
_last_nominatim_call = 0.0


def extract_postcode(text: str) -> str | None:
    match = UK_POSTCODE_FIND_RE.search(text.strip())
    if not match:
        return None
    return normalise_postcode(f'{match.group(1)}{match.group(2)}')


def normalise_postcode(postcode: str) -> str:
    cleaned = re.sub(r'\s+', '', postcode.upper())
    if len(cleaned) > 3:
        return f'{cleaned[:-3]} {cleaned[-3:]}'
    return cleaned


def looks_like_postcode(text: str) -> bool:
    compact = re.sub(r'\s+', '', text.strip())
    return bool(UK_POSTCODE_RE.match(compact))


def _throttle_nominatim() -> None:
    global _last_nominatim_call
    elapsed = time.monotonic() - _last_nominatim_call
    if elapsed < 1.05:
        time.sleep(1.05 - elapsed)
    _last_nominatim_call = time.monotonic()


def reverse_street_name(lat: float, lng: float) -> dict[str, str] | None:
    """Nearest road / place label from OpenStreetMap (free)."""
    _throttle_nominatim()
    try:
        response = requests.get(
            'https://nominatim.openstreetmap.org/reverse',
            params={
                'lat': lat,
                'lon': lng,
                'format': 'json',
                'zoom': 18,
                'addressdetails': 1,
            },
            headers={'User-Agent': USER_AGENT},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return None

    address = data.get('address') or {}
    road = (
        address.get('road')
        or address.get('residential')
        or address.get('pedestrian')
        or address.get('footway')
        or ''
    )
    place = (
        address.get('village')
        or address.get('town')
        or address.get('suburb')
        or address.get('city_district')
        or address.get('city')
        or address.get('municipality')
        or ''
    )
    if not road and not place:
        return None
    return {'road': road, 'place': place}


def format_postcode_display(
    postcode: str,
    *,
    road: str = '',
    place: str = '',
    fallback_place: str = '',
) -> str:
    normalised = normalise_postcode(postcode)
    place = place or fallback_place
    if road and place:
        return f'{road}, {place} · {normalised}'
    if road:
        return f'{road} · {normalised}'
    if place:
        return f'{place} · {normalised}'
    return normalised


def geocode_postcode(postcode: str) -> dict[str, Any] | None:
    normalised = normalise_postcode(postcode)
    url = f'https://api.postcodes.io/postcodes/{requests.utils.quote(normalised)}'
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
    except requests.RequestException:
        return None

    if data.get('status') != 200 or not data.get('result'):
        return None

    result = data['result']
    lat = float(result['latitude'])
    lng = float(result['longitude'])

    fallback_place = (
        result.get('parish')
        or result.get('admin_ward')
        or result.get('admin_district')
        or ''
    )
    # Prefer a real settlement name over "unparished area"
    if 'unparished' in fallback_place.lower():
        fallback_place = result.get('admin_ward') or result.get('admin_district') or ''

    street = reverse_street_name(lat, lng) or {}
    display = format_postcode_display(
        normalised,
        road=street.get('road', ''),
        place=street.get('place', ''),
        fallback_place=fallback_place,
    )

    return {
        'lat': lat,
        'lng': lng,
        'display': display,
        'road': street.get('road', ''),
        'place': street.get('place', '') or fallback_place,
        'postcode': normalised,
        'source': 'postcodes.io',
    }


def geocode_nominatim(query: str) -> dict[str, Any] | None:
    _throttle_nominatim()
    try:
        response = requests.get(
            'https://nominatim.openstreetmap.org/search',
            params={
                'q': query,
                'format': 'json',
                'limit': 1,
                'countrycodes': 'gb',
                'addressdetails': 1,
            },
            headers={'User-Agent': USER_AGENT},
            timeout=15,
        )
        response.raise_for_status()
        results = response.json()
    except requests.RequestException:
        return None

    if not results:
        return None

    hit = results[0]
    address = hit.get('address') or {}
    road = address.get('road') or ''
    place = (
        address.get('village')
        or address.get('town')
        or address.get('suburb')
        or address.get('city')
        or ''
    )
    return {
        'lat': float(hit['lat']),
        'lng': float(hit['lon']),
        'display': hit.get('display_name', query),
        'road': road,
        'place': place,
        'source': 'nominatim',
    }


def geocode_location(location: str) -> dict[str, Any] | None:
    """Geocode a postcode or free-text UK address."""
    text = location.strip()
    if not text:
        return None

    # Always prefer postcodes.io for postcode-shaped input (spaced or not).
    # Never use Nominatim search for bare postcodes — it can latch onto POIs.
    if looks_like_postcode(text):
        return geocode_postcode(text)

    postcode = extract_postcode(text)
    if postcode and looks_like_postcode(postcode):
        result = geocode_postcode(postcode)
        if result:
            # Keep typed address text if user entered more than the postcode
            if len(re.sub(r'\s+', '', text)) > len(re.sub(r'\s+', '', postcode)) + 2:
                result = {
                    **result,
                    'display': f'{text.strip()} · {result.get("road") or result["postcode"]}',
                }
            return result

    return geocode_nominatim(text)
