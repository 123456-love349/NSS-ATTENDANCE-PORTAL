"""
utils/location.py
Reverse geocoding + geo-distance helpers.

Uses geopy's Nominatim (OpenStreetMap) geocoder. Network access can be
unreliable/blocked in sandboxed or offline deployments, so every public
function degrades gracefully instead of raising -- attendance must never
crash just because the geocoding API timed out.
"""

import math

try:
    from geopy.geocoders import Nominatim
    from geopy.exc import GeopyError
except ImportError:  # pragma: no cover - runtime fallback when dependency is absent
    Nominatim = None
    GeopyError = Exception

from flask import current_app

_geolocator = None


def _get_geolocator():
    global _geolocator
    if _geolocator is None:
        if Nominatim is None:
            return None
        user_agent = current_app.config.get("GEOCODER_USER_AGENT", "nss-attendance-system")
        _geolocator = Nominatim(user_agent=user_agent, timeout=6)
    return _geolocator


def reverse_geocode(latitude, longitude):
    """Return a human-readable full address string for given coordinates.

    Falls back to a formatted coordinate string if the geocoding service is
    unreachable, so callers always get *something* displayable.
    """
    if latitude is None or longitude is None:
        return None
    try:
        geolocator = _get_geolocator()
        if geolocator is None:
            return f"Coordinates: {latitude:.6f}, {longitude:.6f} (address lookup unavailable)"
        location = geolocator.reverse((latitude, longitude), language="en", exactly_one=True)
        if location:
            addr = location.raw.get("address", {})
            parts = []
            
            # 1. Amenity / Institution / Department / Building
            amenities = []
            for key in ["amenity", "building", "office", "school", "university", "college", "department", "hospital", "library", "stadium"]:
                if key in addr and addr[key] not in amenities:
                    amenities.append(addr[key])
            if amenities:
                parts.append(", ".join(amenities))
            
            # 2. Road / Street
            if "road" in addr:
                parts.append(addr["road"])
            
            # 3. Suburb / Locality / District
            local_parts = []
            for key in ["suburb", "neighbourhood", "locality", "city_district", "quarter"]:
                if key in addr and addr[key] not in local_parts and addr[key] not in amenities:
                    local_parts.append(addr[key])
            if local_parts:
                parts.append(", ".join(local_parts))
            
            # 4. City / Town / Village
            city_parts = []
            for key in ["city", "town", "village", "municipality", "county"]:
                if key in addr and addr[key] not in city_parts:
                    city_parts.append(addr[key])
            if city_parts:
                parts.append(", ".join(city_parts))
            
            # 5. State / Province
            if "state" in addr:
                parts.append(addr["state"])
            
            # 6. Country
            if "country" in addr:
                parts.append(addr["country"])
                
            if parts:
                return ",\n".join(parts)
            return location.address
    except Exception:  # noqa: BLE001 - never let geocoding break attendance
        pass
    return f"Coordinates: {latitude:.6f}, {longitude:.6f} (address lookup unavailable)"


def build_google_maps_link(latitude, longitude):
    if latitude is None or longitude is None:
        return None
    return f"https://www.google.com/maps?q={latitude},{longitude}"


def haversine_distance_meters(lat1, lon1, lat2, lon2):
    """Great-circle distance between two lat/lon points, in meters."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    R = 6371000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def is_location_suspicious(latitude, longitude, venue_lat, venue_lon, threshold_m):
    """True if the attendee's coordinates are farther than `threshold_m`
    from the event venue's registered coordinates. Returns False (not
    suspicious) if venue coordinates were never set, since there's nothing
    to compare against."""
    if venue_lat is None or venue_lon is None:
        return False
    distance = haversine_distance_meters(latitude, longitude, venue_lat, venue_lon)
    if distance is None:
        return False
    return distance > threshold_m
