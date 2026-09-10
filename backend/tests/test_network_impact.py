"""Integration tests for the network-intelligence orchestration (modules 38, 41) against
the real seeded network. Each `analyze_train_impact`/`analyze_network` call is expensive
in this dev environment (no Redis => ~8s connection-retry overhead per ETA sub-call), so
tests share results via module-scoped fixtures rather than recomputing per assertion.
"""

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.network import impact
from app.network.schemas import ImpactSeverity, NetworkAnalysisStatus
from app.services.exceptions import NotFoundError

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def delayed_train_impact(seeded_session: AsyncSession):
    """Train 12951 has a real seeded delay (SIGNAL_HALT, nominally +15 min) — a genuine
    propagation source against the real network. Note: this dev database is shared with
    other concurrent tooling/sessions, so the exact delay_minutes on its latest event
    isn't asserted as a hardcoded constant here — only that it's positive, matching the
    seed scenario's intent (a delayed train that should propagate).
    """
    return await impact.analyze_train_impact(seeded_session, "12951", date.today())


async def test_impact_identifies_affected_trains(delayed_train_impact) -> None:
    assert delayed_train_impact.analysis_status == NetworkAnalysisStatus.OK
    assert delayed_train_impact.source_delay_minutes > 0
    # Every affected train must be a real train, distinct from the source itself.
    numbers = {a.train_number for a in delayed_train_impact.affected_trains}
    assert "12951" not in numbers


async def test_impact_affected_trains_never_exceed_shared_section_evidence(delayed_train_impact) -> None:
    """Module 5: only relationships actually supported by shared-section + temporal data
    — every affected train must trace back to a real conflict on a real shared section."""
    conflict_pairs = {(c.train_a, c.train_b) for c in delayed_train_impact.conflicts}
    conflict_pairs |= {(b, a) for a, b in conflict_pairs}
    for affected in delayed_train_impact.affected_trains:
        assert ("12951", affected.train_number) in conflict_pairs


async def test_impact_identifies_affected_stations(delayed_train_impact) -> None:
    for station in delayed_train_impact.affected_stations:
        assert station.station_code
        assert station.affected_train_count >= 1
        assert station.latitude is not None and station.longitude is not None


async def test_impact_identifies_affected_sections(delayed_train_impact) -> None:
    for section in delayed_train_impact.affected_sections:
        assert "-" in section.section_code
        assert section.affected_trains >= 1


async def test_impact_score_and_severity_are_consistent(delayed_train_impact) -> None:
    assert 0 <= delayed_train_impact.network_impact_score <= 100
    assert delayed_train_impact.severity in ImpactSeverity
    if delayed_train_impact.network_impact_score >= 75:
        assert delayed_train_impact.severity == ImpactSeverity.CRITICAL
    elif delayed_train_impact.network_impact_score == 0:
        assert delayed_train_impact.severity == ImpactSeverity.LOW


async def test_impact_uses_predictive_language_not_certainty(delayed_train_impact) -> None:
    """Module 46: no conflict/reason may claim a guaranteed or confirmed outcome."""
    for conflict in delayed_train_impact.conflicts:
        text = conflict.reason.description.lower()
        assert "will be delayed" not in text
        assert "guaranteed" not in text
        assert "confirmed" not in text


async def test_train_with_no_delay_returns_zero_impact_not_error(seeded_session: AsyncSession) -> None:
    # Train 14217 has no seeded events at all -> zero known delay.
    result = await impact.analyze_train_impact(seeded_session, "14217", date.today())
    assert result.source_delay_minutes == 0.0
    assert result.network_impact_score == 0
    assert result.severity == ImpactSeverity.LOW
    assert result.affected_trains == []


async def test_unknown_train_raises_not_found(seeded_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await impact.analyze_train_impact(seeded_session, "99999", date.today())


@pytest.fixture
async def network_overview(seeded_session: AsyncSession):
    return await impact.analyze_network(seeded_session, date.today())


async def test_network_overview_counts_are_sane(network_overview) -> None:
    assert network_overview.total_trains_monitored >= 7  # at least the seeded set
    assert network_overview.delayed_trains >= 1  # 12951/11077/12002/12615 all have events
    assert 0 <= network_overview.network_impact_score <= 100


async def test_network_hotspots_are_sorted_by_impact_score(network_overview) -> None:
    scores = [h.impact_score for h in network_overview.hotspots]
    assert scores == sorted(scores, reverse=True)


async def test_network_hotspots_have_valid_entity_types(network_overview) -> None:
    for hotspot in network_overview.hotspots:
        assert hotspot.entity_type in ("STATION", "SECTION")


async def test_network_timeline_buckets_cover_the_horizon(seeded_session: AsyncSession) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    buckets = await impact.get_timeline(seeded_session, date.today(), bucket_minutes=60)
    assert len(buckets) == -(-settings.NETWORK_ANALYSIS_HORIZON_MINUTES // 60)
    for bucket in buckets:
        assert bucket.affected_trains >= 0
        assert bucket.conflicts >= 0
