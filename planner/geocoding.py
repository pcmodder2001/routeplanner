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


def getaddress_api_key() -> str:
    """Royal Mail PAF lookup via getAddress.io — lists every address at a postcode."""
    return (os.environ.get('GETADDRESS_API_KEY') or '').strip()


def address_lookup_enabled() -> bool:
    return bool(google_maps_key() or getaddress_api_key())


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
        if 'street_number' in types:
            mapped['street_number'] = name
        elif 'route' in types:
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


HOUSE_NUMBER_RE = re.compile(
    r'\b(\d+[A-Za-z]?(?:\s*[-/]\s*\d+[A-Za-z]?)?)\b'
)


def parse_postcode_and_number(text: str) -> tuple[str | None, str | None]:
    """
    Pull a UK postcode and house number from free text.

    Examples:
      'Wf169pf 22'      -> ('WF16 9PF', '22')
      '22 WF16 9PF'     -> ('WF16 9PF', '22')
      '22, WF16 9PF'    -> ('WF16 9PF', '22')
      'WF16 9PF'        -> ('WF16 9PF', None)
    """
    raw = text.strip()
    postcode = extract_postcode(raw)
    if not postcode:
        return None, None

    # Remove postcode (spaced or compact) from the string
    remainder = re.sub(
        re.escape(postcode).replace(r'\ ', r'\s*'),
        ' ',
        raw,
        count=1,
        flags=re.IGNORECASE,
    )
    remainder = re.sub(r'[,\s]+', ' ', remainder).strip()
    if not remainder:
        return postcode, None

    match = HOUSE_NUMBER_RE.search(remainder)
    if not match:
        return postcode, None
    return postcode, match.group(1).replace(' ', '')


def format_full_address(
    *,
    street_number: str = '',
    road: str = '',
    place: str = '',
    postcode: str = '',
) -> str:
    line = ' '.join(p for p in [street_number, road] if p).strip()
    bits = [b for b in [line, place, postcode] if b]
    if line and place and postcode:
        return f'{line}, {place} · {postcode}'
    if line and postcode:
        return f'{line} · {postcode}'
    return ', '.join(bits)


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
    street_number = parts.get('street_number', '')
    road = parts.get('road', '')
    place = parts.get('place') or parts.get('district') or ''
    postcode = parts.get('postcode') or extract_postcode(formatted) or ''

    if street_number and road:
        display = format_full_address(
            street_number=street_number,
            road=road,
            place=place,
            postcode=postcode,
        )
    elif looks_like_postcode(query) and (road or place):
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
        'street_number': street_number,
        'source': 'google',
    }


def geocode_postcode_with_number(postcode: str, number: str) -> dict[str, Any] | None:
    """
    Resolve '22 + WF16 9PF' style input to a full premise address.

    Google often ignores the number on postcode-only queries, so we:
    1) geocode the postcode to learn the street
    2) geocode '{number} {street}, {postcode}'
    """
    base = geocode_postcode(postcode) if not google_maps_key() else google_geocode(postcode)
    if not base:
        base = geocode_postcode(postcode)
    if not base:
        return None

    road = base.get('road') or ''
    place = base.get('place') or ''
    pc = base.get('postcode') or normalise_postcode(postcode)

    candidates = []
    if road:
        candidates.append(f'{number} {road}, {pc}')
        if place:
            candidates.append(f'{number} {road}, {place}, {pc}')
    candidates.append(f'{number}, {pc}')
    candidates.append(f'{number} {pc}')

    for query in candidates:
        result = google_geocode(query)
        if not result:
            continue
        # Prefer results that actually resolved a street number
        if result.get('street_number') or (
            result.get('road') and number.lower() in (result.get('display') or '').lower()
        ):
            if not result.get('street_number'):
                result = {
                    **result,
                    'street_number': number,
                    'display': format_full_address(
                        street_number=number,
                        road=result.get('road') or road,
                        place=result.get('place') or place,
                        postcode=result.get('postcode') or pc,
                    )[:255],
                }
            return result

    # Fall back: keep postcode location but label with the number + street we know
    if road:
        return {
            **base,
            'street_number': number,
            'display': format_full_address(
                street_number=number,
                road=road,
                place=place,
                postcode=pc,
            )[:255],
            'source': base.get('source', 'google'),
        }
    return base


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


def _is_postcode_only_query(text: str) -> bool:
    """True when input is a postcode, optionally with a house number — no street name."""
    postcode, number = parse_postcode_and_number(text)
    if not postcode:
        return False
    remainder = re.sub(
        re.escape(postcode).replace(r'\ ', r'\s*'),
        ' ',
        text.strip(),
        count=1,
        flags=re.IGNORECASE,
    )
    if number:
        remainder = re.sub(re.escape(number), ' ', remainder, count=1, flags=re.IGNORECASE)
    remainder = re.sub(r'[,\s]+', ' ', remainder).strip()
    return not bool(re.search(r'[A-Za-z]', remainder))


def _clean_getaddress_csv(raw: str) -> str:
    parts = [p.strip() for p in raw.split(',')]
    return ', '.join(p for p in parts if p)


def _format_getaddress_expanded(addr: dict, postcode: str) -> tuple[str, str, str]:
    """Return (display, main_text, secondary_text) from an expanded getAddress row."""
    line1 = (addr.get('line_1') or '').strip()
    line2 = (addr.get('line_2') or '').strip()
    town = (addr.get('town_or_city') or addr.get('locality') or '').strip()
    pc = normalise_postcode(postcode)
    main = line1 or _clean_getaddress_csv(
        ', '.join(addr.get('formatted_address') or [])
    )
    secondary_bits = [b for b in [line2, town, pc] if b and b not in main]
    secondary = ', '.join(secondary_bits)
    if line1 and town and pc:
        display = f'{line1}, {town} · {pc}'
    elif line1 and pc:
        display = f'{line1} · {pc}'
    else:
        display = f'{main} · {pc}' if pc else main
    return display[:255], main, secondary


def getaddress_find_postcode(
    postcode: str,
    *,
    house_filter: str | None = None,
) -> list[dict[str, str]]:
    """
    List every delivery point at a UK postcode (Royal Mail PAF via getAddress.io).

    Google Places / Address Validation cannot do this — they do not expose PAF.
    """
    key = getaddress_api_key()
    if not key:
        return []

    compact = re.sub(r'\s+', '', normalise_postcode(postcode))
    url = f'https://api.getAddress.io/find/{requests.utils.quote(compact)}'
    try:
        response = requests.get(
            url,
            params={'api-key': key, 'expand': 'true', 'sort': 'true'},
            timeout=15,
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        logger.exception('getAddress find failed for %r', postcode)
        return []

    lat = data.get('latitude')
    lng = data.get('longitude')
    pc = data.get('postcode') or normalise_postcode(postcode)
    suggestions: list[dict[str, str]] = []
    house_filter = (house_filter or '').strip().lower()

    for addr in data.get('addresses') or []:
        if isinstance(addr, str):
            cleaned = _clean_getaddress_csv(addr)
            display = f'{cleaned} · {pc}' if pc else cleaned
            main = cleaned
            secondary = pc
            building_number = ''
        else:
            display, main, secondary = _format_getaddress_expanded(addr, pc)
            building_number = str(addr.get('building_number') or '').strip().lower()

        if house_filter:
            hay = f'{main} {display} {building_number}'.lower()
            # Match "22", "22a", or leading digits the user typed
            if house_filter not in hay and not building_number.startswith(house_filter):
                if not main.lower().startswith(house_filter):
                    continue

        item: dict[str, str] = {
            'place_id': '',
            'description': display,
            'main_text': main,
            'secondary_text': secondary or 'Select address',
            'display': display,
            'source': 'getaddress',
        }
        if lat is not None and lng is not None:
            item['lat'] = str(lat)
            item['lng'] = str(lng)
        suggestions.append(item)

    return suggestions


def address_autocomplete(query: str, *, session_token: str = '') -> list[dict[str, str]]:
    """
    Suggestions for the add-job field.

    - Complete postcode (+ optional house number) → getAddress list of all premises
    - Otherwise → Google Places (street / free-text)
    """
    search = query.strip()
    if len(search) < 3:
        return []

    postcode, number = parse_postcode_and_number(search)
    if postcode and getaddress_api_key() and _is_postcode_only_query(search):
        found = getaddress_find_postcode(postcode, house_filter=number)
        if found:
            return found
        # Fall through if getAddress empty / failed

    return google_places_autocomplete(search, session_token=session_token)


def google_places_autocomplete(query: str, *, session_token: str = '') -> list[dict[str, str]]:
    """Return place suggestions for UK addresses/postcodes."""
    key = google_maps_key()
    if not key or len(query.strip()) < 3:
        return []

    search = query.strip()
    postcode, number = parse_postcode_and_number(search)
    # Rewrite "WF169PF 22" into something Google Places resolves better
    if postcode and number:
        search = f'{number}, {postcode}'

    params = {
        'input': search,
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

    # If Places found nothing but we have postcode+number, synthesise a hint
    # from geocoding so the UI still helps.
    if not suggestions and postcode and number:
        resolved = geocode_postcode_with_number(postcode, number)
        if resolved:
            suggestions.append(
                {
                    'place_id': '',
                    'description': resolved['display'],
                    'main_text': resolved['display'],
                    'secondary_text': 'Resolved address',
                    'lat': str(resolved['lat']),
                    'lng': str(resolved['lng']),
                    'display': resolved['display'],
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
    """Geocode a postcode, postcode+number, or free-text UK address."""
    text = location.strip()
    if not text:
        return None

    postcode, number = parse_postcode_and_number(text)
    if postcode and number:
        result = geocode_postcode_with_number(postcode, number)
        if result:
            return result

    # Google first when keyed — handles addresses and postcodes well
    if google_maps_key():
        result = google_geocode(text)
        if result:
            return result

    if looks_like_postcode(text):
        return geocode_postcode(text)

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
