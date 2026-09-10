from datetime import datetime, time, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.models.enums import (
    AlertSeverity,
    AlertType,
    EventSource,
    EventType,
    PredictionMode,
    StationType,
    TrainPriority,
    TrainType,
)
from app.models.prediction import Prediction
from app.models.route import TrainRoute
from app.models.section import RailwaySection
from app.models.station import Station
from app.models.train import Train
from app.models.train_event import TrainEvent

pytestmark = pytest.mark.asyncio


async def _make_station(session: AsyncSession, code: str, name: str) -> Station:
    station = Station(
        station_code=code,
        station_name=name,
        latitude=Decimal("20.000000"),
        longitude=Decimal("77.000000"),
        zone="ZZ",
        station_type=StationType.REGULAR,
    )
    session.add(station)
    await session.flush()
    return station


async def _make_section(session: AsyncSession, code: str, from_station: Station, to_station: Station) -> RailwaySection:
    section = RailwaySection(
        section_code=code,
        from_station_id=from_station.id,
        to_station_id=to_station.id,
        distance_km=Decimal("50.00"),
        scheduled_running_minutes=40,
        average_running_minutes=45,
        speed_limit_kmph=100,
        zone="ZZ",
    )
    session.add(section)
    await session.flush()
    return section


async def _make_train(session: AsyncSession, number: str, source: Station, destination: Station) -> Train:
    train = Train(
        train_number=number,
        train_name=f"Test Train {number}",
        train_type=TrainType.EXPRESS,
        source_station_id=source.id,
        destination_station_id=destination.id,
        zone="ZZ",
        priority=TrainPriority.NORMAL,
        active=True,
    )
    session.add(train)
    await session.flush()
    return train


# --- 1. Station creation -----------------------------------------------------

async def test_station_creation(db_session: AsyncSession) -> None:
    station = await _make_station(db_session, "TST1", "Test Station One")
    assert station.id is not None
    assert station.station_type == StationType.REGULAR
    assert station.created_at is not None


# --- 2. Unique station code ---------------------------------------------------

async def test_station_code_must_be_unique(db_session: AsyncSession) -> None:
    await _make_station(db_session, "TST2", "Test Station Two")
    with pytest.raises(IntegrityError):
        await _make_station(db_session, "TST2", "Duplicate Code Station")


# --- 3. Train creation ---------------------------------------------------------

async def test_train_creation(db_session: AsyncSession) -> None:
    origin = await _make_station(db_session, "TSA", "Test Origin")
    dest = await _make_station(db_session, "TSB", "Test Destination")
    train = await _make_train(db_session, "T0001", origin, dest)

    assert train.id is not None
    assert train.active is True
    assert train.priority == TrainPriority.NORMAL


# --- 4. Unique train number -----------------------------------------------------

async def test_train_number_must_be_unique(db_session: AsyncSession) -> None:
    origin = await _make_station(db_session, "TSC", "Test Origin C")
    dest = await _make_station(db_session, "TSD", "Test Destination D")
    await _make_train(db_session, "T0002", origin, dest)

    with pytest.raises(IntegrityError):
        await _make_train(db_session, "T0002", origin, dest)


# --- 5. Railway section relationship --------------------------------------------

async def test_railway_section_connects_two_distinct_stations(db_session: AsyncSession) -> None:
    a = await _make_station(db_session, "TSE", "Test Station E")
    b = await _make_station(db_session, "TSF", "Test Station F")
    section = await _make_section(db_session, "TSE-TSF", a, b)

    await db_session.refresh(section, attribute_names=["from_station", "to_station"])
    assert section.from_station.station_code == "TSE"
    assert section.to_station.station_code == "TSF"
    assert section.from_station_id != section.to_station_id


async def test_railway_section_rejects_identical_stations(db_session: AsyncSession) -> None:
    a = await _make_station(db_session, "TSG", "Test Station G")
    with pytest.raises(IntegrityError):
        await _make_section(db_session, "TSG-TSG", a, a)


# --- 6. Train route ordering -----------------------------------------------------

async def test_train_route_sequence_is_ordered(db_session: AsyncSession) -> None:
    a = await _make_station(db_session, "TSH", "Test Station H")
    b = await _make_station(db_session, "TSI", "Test Station I")
    c = await _make_station(db_session, "TSJ", "Test Station J")
    train = await _make_train(db_session, "T0003", a, c)
    section_ab = await _make_section(db_session, "TSH-TSI", a, b)
    section_bc = await _make_section(db_session, "TSI-TSJ", b, c)

    db_session.add_all(
        [
            TrainRoute(
                train_id=train.id, station_id=a.id, section_id=None, sequence_number=1,
                scheduled_departure=time(8, 0), day_offset=0, halt_minutes=0, distance_from_origin_km=Decimal("0.00"),
            ),
            TrainRoute(
                train_id=train.id, station_id=b.id, section_id=section_ab.id, sequence_number=2,
                scheduled_arrival=time(8, 40), scheduled_departure=time(8, 45), day_offset=0, halt_minutes=5,
                distance_from_origin_km=Decimal("50.00"),
            ),
            TrainRoute(
                train_id=train.id, station_id=c.id, section_id=section_bc.id, sequence_number=3,
                scheduled_arrival=time(9, 25), day_offset=0, halt_minutes=0, distance_from_origin_km=Decimal("100.00"),
            ),
        ]
    )
    await db_session.flush()

    result = await db_session.execute(
        select(TrainRoute).where(TrainRoute.train_id == train.id).order_by(TrainRoute.sequence_number)
    )
    ordered = list(result.scalars().all())
    assert [r.station_id for r in ordered] == [a.id, b.id, c.id]
    assert [r.sequence_number for r in ordered] == [1, 2, 3]


# --- 7. Train route uniqueness ----------------------------------------------------

async def test_train_route_sequence_number_unique_per_train(db_session: AsyncSession) -> None:
    a = await _make_station(db_session, "TSK", "Test Station K")
    b = await _make_station(db_session, "TSL", "Test Station L")
    train = await _make_train(db_session, "T0004", a, b)

    db_session.add(
        TrainRoute(
            train_id=train.id, station_id=a.id, sequence_number=1, day_offset=0,
            halt_minutes=0, distance_from_origin_km=Decimal("0.00"),
        )
    )
    await db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.add(
            TrainRoute(
                train_id=train.id, station_id=b.id, sequence_number=1, day_offset=0,
                halt_minutes=0, distance_from_origin_km=Decimal("10.00"),
            )
        )
        await db_session.flush()


# --- 8. Train event creation --------------------------------------------------------

async def test_train_event_creation(db_session: AsyncSession) -> None:
    a = await _make_station(db_session, "TSM", "Test Station M")
    b = await _make_station(db_session, "TSN", "Test Station N")
    train = await _make_train(db_session, "T0005", a, b)

    event = TrainEvent(
        train_id=train.id,
        timestamp=datetime.now(timezone.utc),
        station_id=a.id,
        delay_minutes=12,
        event_type=EventType.POSITION_UPDATE,
        event_source=EventSource.SIMULATOR,
        event_metadata={"note": "test event"},
    )
    db_session.add(event)
    await db_session.flush()

    assert event.id is not None
    assert event.delay_minutes == 12
    assert event.event_metadata == {"note": "test event"}


# --- 9. Prediction creation ------------------------------------------------------------

async def test_prediction_creation(db_session: AsyncSession) -> None:
    a = await _make_station(db_session, "TSO", "Test Station O")
    b = await _make_station(db_session, "TSP", "Test Station P")
    train = await _make_train(db_session, "T0006", a, b)

    prediction = Prediction(
        train_id=train.id,
        station_id=b.id,
        prediction_timestamp=datetime.now(timezone.utc),
        confidence=Decimal("0.850"),
        prediction_mode=PredictionMode.BASELINE_FALLBACK,
    )
    db_session.add(prediction)
    await db_session.flush()

    assert prediction.id is not None
    assert prediction.final_eta is None  # not computed until Phase 8+
    assert prediction.prediction_mode == PredictionMode.BASELINE_FALLBACK


# --- 10. Alert creation -------------------------------------------------------------------

async def test_alert_creation(db_session: AsyncSession) -> None:
    a = await _make_station(db_session, "TSQ", "Test Station Q")
    b = await _make_station(db_session, "TSR", "Test Station R")
    train = await _make_train(db_session, "T0007", a, b)

    alert = Alert(
        alert_type=AlertType.TRAIN_DELAY,
        severity=AlertSeverity.WARNING,
        train_id=train.id,
        title="Test train running late",
        description="Delay exceeded threshold in a test scenario",
        alert_metadata={"delay_minutes": 18},
    )
    db_session.add(alert)
    await db_session.flush()

    assert alert.id is not None
    assert alert.resolved_at is None
    assert alert.alert_metadata == {"delay_minutes": 18}


async def test_alert_allows_null_train_for_section_level_alerts(db_session: AsyncSession) -> None:
    a = await _make_station(db_session, "TSS", "Test Station S")
    b = await _make_station(db_session, "TST", "Test Station T")
    section = await _make_section(db_session, "TSS-TST", a, b)

    alert = Alert(
        alert_type=AlertType.CONGESTION,
        severity=AlertSeverity.INFO,
        section_id=section.id,
        title="Section congestion (test)",
    )
    db_session.add(alert)
    await db_session.flush()

    assert alert.id is not None
    assert alert.train_id is None
