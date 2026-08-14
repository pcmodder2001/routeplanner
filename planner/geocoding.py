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


def ideal_postcodes_api_key() -> str:
    """
    Royal Mail PAF lookup via Ideal Postcodes.

    getAddress.io shut down Feb 2026 — only Ideal keys (usually start with ak_) work.
    Legacy GETADDRESS_API_KEY is accepted when it looks like an Ideal key.
    """
    ideal = (os.environ.get('IDEAL_POSTCODES_API_KEY') or '').strip()
    if ideal:
        return ideal
    legacy = (os.environ.get('GETADDRESS_API_KEY') or '').strip()
    # Ideal keys are typically ak_... ; old getAddress keys are not usable anymore
    if legacy.startswith('ak_'):
        return legacy
    return ''


def getaddress_api_key() -> str:
    """Back-compat alias for Ideal Postcodes key."""
    return ideal_postcodes_api_key()


def address_lookup_enabled() -> bool:
    return bool(google_maps_key() or ideal_postcodes_api_key())


def paf_lookup_enabled() -> bool:
    return bool(ideal_postcodes_api_key())


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


def _clean_address_csv(raw: str) -> str:
    parts = [p.strip() for p in raw.split(',')]
    return ', '.join(p for p in parts if p)


def _format_paf_address(
    *,
    line1: str,
    line2: str = '',
    town: str = '',
    postcode: str = '',
) -> tuple[str, str, str]:
    pc = normalise_postcode(postcode) if postcode else ''
    main = (line1 or '').strip()
    secondary_bits = [b for b in [line2, town, pc] if b and b not in main]
    secondary = ', '.join(secondary_bits)
    if main and town and pc:
        display = f'{main}, {town} · {pc}'
    elif main and pc:
        display = f'{main} · {pc}'
    else:
        display = f'{main} · {pc}' if pc else main
    return display[:255], main, secondary


def _house_matches(house_filter: str, *, building_number: str, line1: str, display: str) -> bool:
    """Match typed door number against a PAF row (exact, prefix, or contained)."""
    filt = house_filter.strip().lower()
    if not filt:
        return True
    bn = (building_number or '').strip().lower()
    line = (line1 or '').strip().lower()
    hay = f'{line} {display}'.lower()
    if bn == filt or bn.startswith(filt):
        return True
    if line.startswith(filt) or f' {filt} ' in f' {hay} ':
        return True
    # "22" should match "22a" / "Flat 22"
    if re.search(rf'(?:^|[\s,]){re.escape(filt)}[a-z]?\b', hay):
        return True
    return False


def _suggestion_from_resolved(resolved: dict[str, Any]) -> dict[str, str]:
    display = resolved['display']
    return {
        'place_id': '',
        'description': display,
        'main_text': display,
        'secondary_text': 'Tap to select',
        'lat': str(resolved['lat']),
        'lng': str(resolved['lng']),
        'display': display,
        'source': resolved.get('source', 'resolved'),
    }


def ideal_find_postcode(
    postcode: str,
    *,
    house_filter: str | None = None,
) -> list[dict[str, str]]:
    """List every delivery point at a UK postcode via Ideal Postcodes."""
    key = ideal_postcodes_api_key()
    if not key:
        return []

    compact = re.sub(r'\s+', '', normalise_postcode(postcode))
    url = f'https://api.ideal-postcodes.co.uk/v1/postcodes/{requests.utils.quote(compact)}'
    try:
        response = requests.get(url, params={'api_key': key}, timeout=15)
        if response.status_code in (404, 401, 402, 403):
            logger.info(
                'Ideal Postcodes status=%s for %r',
                response.status_code,
                postcode,
            )
            return []
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        logger.exception('Ideal Postcodes lookup failed for %r', postcode)
        return []

    # Native Ideal: { code, result: [ {...}, ... ] }
    # Compat/getAddress style may nest differently
    results = data.get('result')
    if results is None and isinstance(data.get('addresses'), list):
        results = data['addresses']
    if not isinstance(results, list):
        return []

    suggestions: list[dict[str, str]] = []
    for addr in results:
        if isinstance(addr, str):
            cleaned = _clean_address_csv(addr)
            pc = normalise_postcode(postcode)
            display = f'{cleaned} · {pc}'
            main, secondary, building_number = cleaned, pc, ''
            lat = lng = None
        else:
            line1 = (addr.get('line_1') or '').strip()
            line2 = (addr.get('line_2') or '').strip()
            town = (
                addr.get('post_town')
                or addr.get('town_or_city')
                or addr.get('dependant_locality')
                or ''
            ).strip()
            pc = (addr.get('postcode') or normalise_postcode(postcode)).strip()
            display, main, secondary = _format_paf_address(
                line1=line1,
                line2=line2,
                town=town,
                postcode=pc,
            )
            building_number = str(
                addr.get('building_number') or addr.get('building_name') or ''
            ).strip()
            lat = addr.get('latitude')
            lng = addr.get('longitude')

        if not _house_matches(
            house_filter or '',
            building_number=building_number,
            line1=main,
            display=display,
        ):
            continue

        item: dict[str, str] = {
            'place_id': '',
            'description': display,
            'main_text': main,
            'secondary_text': secondary or 'Select address',
            'display': display,
            'source': 'ideal-postcodes',
        }
        if lat is not None and lng is not None:
            item['lat'] = str(lat)
            item['lng'] = str(lng)
        suggestions.append(item)

    return suggestions


def getaddress_compat_find_postcode(
    postcode: str,
    *,
    house_filter: str | None = None,
) -> list[dict[str, str]]:
    """
    Ideal Postcodes getAddress-compatible find endpoint.
    Only works with an Ideal Postcodes API key (getAddress.io itself is shut down).
    """
    key = ideal_postcodes_api_key()
    if not key:
        return []

    compact = re.sub(r'\s+', '', normalise_postcode(postcode))
    url = f'https://ga.ideal-postcodes.co.uk/find/{requests.utils.quote(compact)}'
    try:
        response = requests.get(
            url,
            params={'api-key': key, 'expand': 'true', 'sort': 'true'},
            timeout=15,
        )
        if response.status_code in (404, 401, 402, 403):
            return []
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        logger.exception('Ideal compat find failed for %r', postcode)
        return []

    lat = data.get('latitude')
    lng = data.get('longitude')
    pc = data.get('postcode') or normalise_postcode(postcode)
    suggestions: list[dict[str, str]] = []

    for addr in data.get('addresses') or []:
        if isinstance(addr, str):
            cleaned = _clean_address_csv(addr)
            display = f'{cleaned} · {pc}' if pc else cleaned
            main, secondary, building_number = cleaned, pc, ''
        else:
            display, main, secondary = _format_paf_address(
                line1=(addr.get('line_1') or '').strip(),
                line2=(addr.get('line_2') or '').strip(),
                town=(addr.get('town_or_city') or addr.get('locality') or '').strip(),
                postcode=pc,
            )
            building_number = str(addr.get('building_number') or '').strip()

        if not _house_matches(
            house_filter or '',
            building_number=building_number,
            line1=main,
            display=display,
        ):
            continue

        item: dict[str, str] = {
            'place_id': '',
            'description': display,
            'main_text': main,
            'secondary_text': secondary or 'Select address',
            'display': display,
            'source': 'ideal-compat',
        }
        if lat is not None and lng is not None:
            item['lat'] = str(lat)
            item['lng'] = str(lng)
        suggestions.append(item)

    return suggestions


def paf_find_postcode(
    postcode: str,
    *,
    house_filter: str | None = None,
) -> list[dict[str, str]]:
    """Try Ideal native, then getAddress-compat shim."""
    found = ideal_find_postcode(postcode, house_filter=house_filter)
    if found:
        return found
    return getaddress_compat_find_postcode(postcode, house_filter=house_filter)


def address_autocomplete(query: str, *, session_token: str = '') -> list[dict[str, str]]:
    """
    Suggestions for the add-job field.

    - Postcode (+ optional door number) → PAF list when Ideal Postcodes key is set
    - Postcode + door number → Google resolve to full street address
    - Otherwise → Google Places (street / free-text)
    """
    search = query.strip()
    if len(search) < 3:
        return []

    postcode, number = parse_postcode_and_number(search)
    if postcode and _is_postcode_only_query(search):
        if ideal_postcodes_api_key():
            found = paf_find_postcode(postcode, house_filter=number)
            if found:
                return found

        # Door number without working PAF: resolve via Google geocode
        if number:
            resolved = geocode_postcode_with_number(postcode, number)
            if resolved:
                return [_suggestion_from_resolved(resolved)]

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

    suggestions: list[dict[str, str]] = []
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

    # Places often returns only the postcode for "22, WF16 9PF" — prefer a resolved
    # full address when we know the door number.
    if postcode and number:
        resolved = geocode_postcode_with_number(postcode, number)
        if resolved:
            resolved_item = _suggestion_from_resolved(resolved)
            # Drop vague postcode-only predictions that omit the house number
            filtered = [
                s
                for s in suggestions
                if number.lower() in (s.get('description') or '').lower()
                or number.lower() in (s.get('main_text') or '').lower()
            ]
            return [resolved_item] + filtered

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
