"""Impact/severity scoring (modules 16, 17) — a transparent, additive 0-100 score. This
is RAILCAST's own analytical score, not an official railway risk classification
(module 16 is explicit about that), and thresholds are fully configurable.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.network.schemas import ImpactSeverity


def severity_for_score(score: int) -> ImpactSeverity:
    settings = get_settings()
    if score >= settings.NETWORK_CRITICAL_IMPACT_THRESHOLD:
        return ImpactSeverity.CRITICAL
    if score >= settings.NETWORK_HIGH_IMPACT_THRESHOLD:
        return ImpactSeverity.HIGH
    if score >= settings.NETWORK_MEDIUM_IMPACT_THRESHOLD:
        return ImpactSeverity.MEDIUM
    return ImpactSeverity.LOW


def train_impact_score(
    *,
    source_delay_minutes: float,
    affected_train_count: int,
    affected_section_count: int,
    affected_station_count: int,
    max_overlap_minutes: float,
    max_propagation_depth: int,
) -> int:
    """Weighted additive score, each component capped so no single factor dominates:

    - source delay itself (up to 30)
    - breadth of impact: trains/sections/stations touched (up to 40 combined)
    - how severe the worst overlap is (up to 20)
    - how far the impact reached (depth reached, up to 10)
    """
    score = 0.0
    score += min(30.0, source_delay_minutes * 1.0)
    score += min(20.0, affected_train_count * 4.0)
    score += min(10.0, affected_section_count * 3.0)
    score += min(10.0, affected_station_count * 3.0)
    score += min(20.0, max_overlap_minutes * 1.0)
    score += min(10.0, max_propagation_depth * 3.0)
    return max(0, min(100, round(score)))


def hotspot_score(*, affected_train_count: int, conflict_count: int, total_estimated_delay: float) -> int:
    """Scores a single station/section as a candidate hotspot (module 18) — how much
    predicted impact converges there, independent of any one train's own impact score.
    """
    score = 0.0
    score += min(50.0, affected_train_count * 10.0)
    score += min(30.0, conflict_count * 10.0)
    score += min(20.0, total_estimated_delay * 0.5)
    return max(0, min(100, round(score)))
