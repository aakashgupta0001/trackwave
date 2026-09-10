"""Predictive alert creation + deduplication (modules 26, 27, 42).

Real seeded data's actual network impact score for train 12951 sits below
NETWORK_ALERT_THRESHOLD (see test_network_impact.py), so alert-creation itself is
exercised directly against `_create_predictive_alerts` with a manually constructed
high-score TrainImpactResponse — the same function `analyze_train_impact` calls once
its computed score crosses the threshold.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.models.enums import AlertSeverity, AlertType
from app.network.impact import _create_predictive_alerts
from app.network.schemas import (
    AffectedTrain,
    ConfidenceLevel,
    ConflictType,
    ImpactReason,
    ImpactSeverity,
    NetworkAnalysisStatus,
    NetworkConflict,
    TrainImpactResponse,
)
from app.repositories import train_repository

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def cleanup_synthetic_alerts(seeded_session: AsyncSession):
    """These tests create real Alert rows via a synthetic 'affected train' (99998, which
    never appears in the seeded network) — clean them up afterward so they don't
    accumulate in the real alerts table across test runs.
    """
    yield
    await seeded_session.execute(
        delete(Alert).where(
            or_(
                Alert.alert_metadata["train_b"].astext == "99998",
                Alert.alert_metadata["affected_trains"].astext.like("%99998%"),
            )
        )
    )
    await seeded_session.commit()

pytestmark = pytest.mark.asyncio


def _high_impact_response(train_number: str, *, section_code: str = "AGC-GWL") -> TrainImpactResponse:
    reason = ImpactReason(
        type="SHARED_SECTION",
        description=f"Train {train_number} is predicted to occupy {section_code} during another train's window.",
        confidence=ConfidenceLevel.MEDIUM,
    )
    return TrainImpactResponse(
        train_number=train_number,
        train_name="Test Train",
        analysis_status=NetworkAnalysisStatus.OK,
        source_delay_minutes=30.0,
        network_impact_score=85,
        severity=ImpactSeverity.CRITICAL,
        affected_trains=[
            AffectedTrain(
                source_train_number=train_number, train_number="99998", train_name="Other Test Train",
                section_code=section_code, station_code="GWL", estimated_delay_minutes=12.0,
                propagation_depth=0, impact_severity=ImpactSeverity.HIGH, impact_confidence=ConfidenceLevel.HIGH,
                reason=reason,
            )
        ],
        affected_stations=[],
        affected_sections=[],
        conflicts=[
            NetworkConflict(
                conflict_type=ConflictType.SHARED_SECTION_OVERLAP, severity=ImpactSeverity.CRITICAL,
                train_a=train_number, train_b="99998", section_code=section_code, station_code="GWL",
                estimated_overlap_minutes=15.0, separation_minutes=0.0,
                directional_confidence=ConfidenceLevel.HIGH, reason=reason,
            )
        ],
        generated_at=datetime.now(timezone.utc),
        horizon_minutes=180,
    )


async def test_high_impact_alert_is_created(seeded_session: AsyncSession) -> None:
    train = await train_repository.get_by_number(seeded_session, "12951")
    response = _high_impact_response("12951")

    await _create_predictive_alerts(seeded_session, train, response)

    result = await seeded_session.execute(
        select(Alert).where(Alert.alert_type == AlertType.HIGH_NETWORK_IMPACT, Alert.train_id == train.id)
    )
    alerts = list(result.scalars().all())
    assert len(alerts) >= 1
    assert alerts[-1].severity == AlertSeverity.CRITICAL
    assert alerts[-1].alert_metadata["network_impact_score"] == 85


async def test_conflict_alert_is_created(seeded_session: AsyncSession) -> None:
    train = await train_repository.get_by_number(seeded_session, "12002")
    response = _high_impact_response("12002", section_code="GWL-JHS")

    await _create_predictive_alerts(seeded_session, train, response)

    # Filtered on train_b="99998" (this fixture's synthetic affected train) too, since
    # a real train_a=12002 conflict alert may already exist from real network analysis
    # (e.g. a manual /network/overview run) — train_a alone isn't a unique-enough filter.
    result = await seeded_session.execute(
        select(Alert).where(
            Alert.alert_type == AlertType.NETWORK_CONFLICT,
            Alert.alert_metadata["train_a"].astext == "12002",
            Alert.alert_metadata["train_b"].astext == "99998",
        )
    )
    alerts = list(result.scalars().all())
    assert len(alerts) >= 1
    assert alerts[-1].alert_metadata["section_code"] == "GWL-JHS"


async def test_repeated_analysis_does_not_duplicate_alerts(seeded_session: AsyncSession) -> None:
    train = await train_repository.get_by_number(seeded_session, "12615")
    response = _high_impact_response("12615", section_code="BINA-BPL")

    await _create_predictive_alerts(seeded_session, train, response)
    result = await seeded_session.execute(
        select(Alert).where(Alert.alert_type == AlertType.HIGH_NETWORK_IMPACT, Alert.train_id == train.id)
    )
    count_after_first = len(list(result.scalars().all()))

    # Same analysis, same hour bucket -> must be deduplicated by fingerprint.
    await _create_predictive_alerts(seeded_session, train, response)
    result = await seeded_session.execute(
        select(Alert).where(Alert.alert_type == AlertType.HIGH_NETWORK_IMPACT, Alert.train_id == train.id)
    )
    count_after_second = len(list(result.scalars().all()))

    assert count_after_second == count_after_first


async def test_alert_metadata_lists_affected_trains(seeded_session: AsyncSession) -> None:
    train = await train_repository.get_by_number(seeded_session, "11077")
    response = _high_impact_response("11077", section_code="AGC-GWL")

    await _create_predictive_alerts(seeded_session, train, response)

    result = await seeded_session.execute(
        select(Alert).where(Alert.alert_type == AlertType.HIGH_NETWORK_IMPACT, Alert.train_id == train.id)
    )
    alert = result.scalars().all()[-1]
    assert "99998" in alert.alert_metadata["affected_trains"]
