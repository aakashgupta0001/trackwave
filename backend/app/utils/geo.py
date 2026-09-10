"""Geographic helpers for the baseline ETA engine (Phase 5).

Straight-line (great-circle) distance only. A straight-line distance is NEVER used as
railway track distance when a better source exists — callers must prefer, in order:
RailwaySection.distance_km → route distance_from_origin_km deltas → an explicitly
labelled geographic approximation (GEOGRAPHIC_APPROXIMATION).
"""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two (latitude, longitude) points in kilometres.

    Raises ValueError on coordinates outside their valid ranges — callers are expected
    to validate/ignore bad GPS data rather than silently propagate nonsense distances.
    """
    for lat, lon in ((lat1, lon1), (lat2, lon2)):
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            raise ValueError(f"Invalid coordinate: lat={lat}, lon={lon}")

    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def fraction_along_section(
    lat: float,
    lon: float,
    from_lat: float,
    from_lon: float,
    to_lat: float,
    to_lon: float,
) -> float:
    """Approximate progress (0.0–1.0) of a point along the straight line between a
    section's endpoint stations, by projecting onto that line in a local planar
    approximation.

    LIMITATION: this ignores real track curvature — with no section geometry available
    (Phase 5 has none), it is a deliberately simple, documented approximation, not a GIS
    computation. The result is clamped to [0, 1].
    """
    # Local equirectangular scaling around the section midpoint keeps the projection
    # planar while staying accurate enough at railway-section scales (<~1000 km).
    mid_lat = math.radians((from_lat + to_lat) / 2)
    kx = math.cos(mid_lat)

    ax, ay = from_lon * kx, from_lat
    bx, by = to_lon * kx, to_lat
    px, py = lon * kx, lat

    abx, aby = bx - ax, by - ay
    denom = abx * abx + aby * aby
    if denom == 0:
        return 0.0
    t = ((px - ax) * abx + (py - ay) * aby) / denom
    return max(0.0, min(1.0, t))
