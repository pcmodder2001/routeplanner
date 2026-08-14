"""UK-friendly geocoding: Google (preferred) → postcodes.io → Nominatim."""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

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


def google_maps_key() -> str:
    return (os.environ.get('GOOGLE_MAPS_API_KEY') or '').strip()


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


def _parse_google_address_components(components: list[dict]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for comp in components:
        types = comp.get('types') or []
        name = comp.get('long_name') or ''
        if 'route' in types:
            mapped['road'] = name
        elif 'postal_town' in types or 'locality' in types:
            mapped.setdefault('place', name)
        elif 'sublocality' in types or 'sublocality_level_1' in types:
            mapped.setdefault('place', name)
        elif 'administrative_area_level_2' in types:
            mapped.setdefault('district', name)
        elif 'postal_code' in types:
            mapped['postcode'] = name
    return mapped


def google_geocode(query: str) -> dict[str, Any] | None:
    key = google_maps_key()
    if not key:
        return None
    try:
        response = requests.get(
            'https://maps.googleapis.com/maps/api/geocode/json',
            params={
                'address': query,
                'components': 'country:GB',
                'region': 'uk',
                'key': key,
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        logger.exception('Google Geocoding failed')
        return None

    if data.get('status') != 'OK' or not data.get('results'):
        logger.info('Google Geocoding status=%s for %r', data.get('status'), query)
        return None

    hit = data['results'][0]
    loc = (hit.get('geometry') or {}).get('location') or {}
    if loc.get('lat') is None or loc.get('lng') is None:
        return None

    parts = _parse_google_address_components(hit.get('address_components') or [])
    formatted = hit.get('formatted_address') or query
    road = parts.get('road', '')
    place = parts.get('place') or parts.get('district') or ''
    postcode = parts.get('postcode') or extract_postcode(formatted) or ''

    if looks_like_postcode(query) and (road or place):
        display = format_postcode_display(
            postcode or query,
            road=road,
            place=place,
        )
    else:
        display = formatted.replace(', UK', '').replace(', United Kingdom', '')

    return {
        'lat': float(loc['lat']),
        'lng': float(loc['lng']),
        'display': display[:255],
        'road': road,
        'place': place,
        'postcode': postcode,
        'source': 'google',
    }


def google_reverse(lat: float, lng: float) -> dict[str, str] | None:
    key = google_maps_key()
    if not key:
        return None
    try:
        response = requests.get(
            'https://maps.googleapis.com/maps/api/geocode/json',
            params={
                'latlng': f'{lat},{lng}',
                'result_type': 'street_address|route',
                'key': key,
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        logger.exception('Google reverse geocode failed')
        return None

    if data.get('status') != 'OK' or not data.get('results'):
        return None

    hit = data['results'][0]
    parts = _parse_google_address_components(hit.get('address_components') or [])
    road = parts.get('road', '')
    place = parts.get('place') or parts.get('district') or ''
    if not road and not place:
        return None
    return {'road': road, 'place': place}


def google_places_autocomplete(query: str, *, session_token: str = '') -> list[dict[str, str]]:
    """Return place suggestions for UK addresses/postcodes."""
    key = google_maps_key()
    if not key or len(query.strip()) < 3:
        return []

    params = {
        'input': query.strip(),
        'components': 'country:gb',
        'types': 'geocode',
        'key': key,
    }
    if session_token:
        params['sessiontoken'] = session_token

    try:
        response = requests.get(
            'https://maps.googleapis.com/maps/api/place/autocomplete/json',
            params=params,
            timeout=12,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        logger.exception('Google Places Autocomplete failed')
        return []

    if data.get('status') not in ('OK', 'ZERO_RESULTS'):
        logger.info('Places Autocomplete status=%s', data.get('status'))
        return []

    suggestions = []
    for pred in data.get('predictions') or []:
        suggestions.append(
            {
                'place_id': pred.get('place_id') or '',
                'description': pred.get('description') or '',
                'main_text': ((pred.get('structured_formatting') or {}).get('main_text') or ''),
                'secondary_text': (
                    (pred.get('structured_formatting') or {}).get('secondary_text') or ''
                ),
            }
        )
    return suggestions


def google_place_details(place_id: str, *, session_token: str = '') -> dict[str, Any] | None:
    key = google_maps_key()
    if not key or not place_id:
        return None

    params = {
        'place_id': place_id,
        'fields': 'geometry,formatted_address,address_component,name',
        'key': key,
    }
    if session_token:
        params['sessiontoken'] = session_token

    try:
        response = requests.get(
            'https://maps.googleapis.com/maps/api/place/details/json',
            params=params,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        logger.exception('Google Place Details failed')
        return None

    if data.get('status') != 'OK' or not data.get('result'):
        return None

    result = data['result']
    loc = ((result.get('geometry') or {}).get('location')) or {}
    if loc.get('lat') is None or loc.get('lng') is None:
        return None

    parts = _parse_google_address_components(result.get('address_components') or [])
    formatted = result.get('formatted_address') or result.get('name') or ''
    display = formatted.replace(', UK', '').replace(', United Kingdom', '')

    return {
        'lat': float(loc['lat']),
        'lng': float(loc['lng']),
        'display': display[:255],
        'road': parts.get('road', ''),
        'place': parts.get('place') or parts.get('district') or '',
        'postcode': parts.get('postcode') or '',
        'source': 'google-places',
    }


def reverse_street_name(lat: float, lng: float) -> dict[str, str] | None:
    """Nearest road / place label — Google first, then Nominatim."""
    google = google_reverse(lat, lng)
    if google:
        return google

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


def geocode_postcode(postcode: str) -> dict[str, Any] | None:
    # Prefer Google when available (better street label for many UK postcodes)
    google = google_geocode(postcode)
    if google:
        return google

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

    # Google first when keyed — handles addresses and postcodes well
    if google_maps_key():
        result = google_geocode(text)
        if result:
            return result

    if looks_like_postcode(text):
        return geocode_postcode(text)

    postcode = extract_postcode(text)
    if postcode and looks_like_postcode(postcode):
        result = geocode_postcode(postcode)
        if result:
            if len(re.sub(r'\s+', '', text)) > len(re.sub(r'\s+', '', postcode)) + 2:
                result = {
                    **result,
                    'display': f'{text.strip()} · {result.get("road") or result["postcode"]}',
                }
            return result

    return geocode_nominatim(text)
