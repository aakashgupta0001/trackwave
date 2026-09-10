"""Repeatable, idempotent seed script for RAILCAST sample data.

Populates a small but realistic Delhi -> Mumbai railway network (with one branch),
a handful of trains running over it, their static timetables, and a few sample
TrainEvent rows for manual inspection.

IMPORTANT: All station distances, running times, and timetable clock times below
are prototype/sample values for demonstration purposes — they are NOT sourced from
official Indian Railways data (NTES/RTIS or otherwise).

Run with:
    python -m scripts.seed
"""

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import setup_logging
from app.db.session import AsyncSessionLocal
from app.models.enums import EventSource, EventType, StationType, TrainPriority, TrainType
from app.models.section import RailwaySection
from app.models.station import Station
from app.models.train import Train
from app.models.train_event import TrainEvent
from app.repositories import event_repository, route_repository, section_repository, station_repository, train_repository
from app.schemas.route import TrainRouteCreate
from app.schemas.section import RailwaySectionCreate
from app.schemas.station import StationCreate
from app.schemas.train import TrainCreate
from app.schemas.train_event import TrainEventCreate

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sample network: New Delhi -> Mumbai CSMT trunk line, with a Jhansi -> Bina ->
# Bhopal branch offered as an alternative to the direct Jhansi -> Bhopal section
# (mirroring how the real Bina Junction sits on that corridor).
# ---------------------------------------------------------------------------

STATIONS: list[dict] = [
    dict(station_code="NDLS", station_name="New Delhi", latitude=28.6432, longitude=77.2196,
         zone="NR", division="Delhi", state="Delhi", station_type=StationType.TERMINAL),
    dict(station_code="MTJ", station_name="Mathura Junction", latitude=27.4924, longitude=77.6737,
         zone="NCR", division="Agra", state="Uttar Pradesh", station_type=StationType.JUNCTION),
    dict(station_code="AGC", station_name="Agra Cantt", latitude=27.1591, longitude=78.0092,
         zone="NCR", division="Agra", state="Uttar Pradesh", station_type=StationType.MAJOR),
    dict(station_code="GWL", station_name="Gwalior", latitude=26.2183, longitude=78.1828,
         zone="NCR", division="Jhansi", state="Madhya Pradesh", station_type=StationType.MAJOR),
    dict(station_code="JHS", station_name="Jhansi Junction", latitude=25.4484, longitude=78.5685,
         zone="NCR", division="Jhansi", state="Uttar Pradesh", station_type=StationType.JUNCTION),
    dict(station_code="BINA", station_name="Bina Junction", latitude=24.1900, longitude=78.1800,
         zone="WCR", division="Bhopal", state="Madhya Pradesh", station_type=StationType.JUNCTION),
    dict(station_code="BPL", station_name="Bhopal Junction", latitude=23.2599, longitude=77.4126,
         zone="WCR", division="Bhopal", state="Madhya Pradesh", station_type=StationType.MAJOR),
    dict(station_code="ET", station_name="Itarsi Junction", latitude=22.6113, longitude=77.7611,
         zone="WCR", division="Bhopal", state="Madhya Pradesh", station_type=StationType.JUNCTION),
    dict(station_code="NGP", station_name="Nagpur", latitude=21.1458, longitude=79.0882,
         zone="CR", division="Nagpur", state="Maharashtra", station_type=StationType.MAJOR),
    dict(station_code="CSMT", station_name="Mumbai CSMT", latitude=18.9398, longitude=72.8355,
         zone="CR", division="Mumbai", state="Maharashtra", station_type=StationType.TERMINAL),
]

# distance_km / scheduled_running_minutes are approximate prototype values.
SECTIONS: list[dict] = [
    dict(section_code="NDLS-MTJ", from_station_code="NDLS", to_station_code="MTJ",
         distance_km=141.0, scheduled_running_minutes=95, speed_limit_kmph=130, zone="NR"),
    dict(section_code="MTJ-AGC", from_station_code="MTJ", to_station_code="AGC",
         distance_km=54.0, scheduled_running_minutes=40, speed_limit_kmph=110, zone="NCR"),
    dict(section_code="AGC-GWL", from_station_code="AGC", to_station_code="GWL",
         distance_km=118.0, scheduled_running_minutes=80, speed_limit_kmph=110, zone="NCR"),
    dict(section_code="GWL-JHS", from_station_code="GWL", to_station_code="JHS",
         distance_km=98.0, scheduled_running_minutes=70, speed_limit_kmph=110, zone="NCR"),
    dict(section_code="JHS-BPL", from_station_code="JHS", to_station_code="BPL",
         distance_km=297.0, scheduled_running_minutes=210, speed_limit_kmph=110, zone="WCR"),
    dict(section_code="JHS-BINA", from_station_code="JHS", to_station_code="BINA",
         distance_km=180.0, scheduled_running_minutes=130, speed_limit_kmph=100, zone="WCR"),
    dict(section_code="BINA-BPL", from_station_code="BINA", to_station_code="BPL",
         distance_km=120.0, scheduled_running_minutes=90, speed_limit_kmph=100, zone="WCR"),
    dict(section_code="BPL-ET", from_station_code="BPL", to_station_code="ET",
         distance_km=92.0, scheduled_running_minutes=70, speed_limit_kmph=110, zone="WCR"),
    dict(section_code="ET-NGP", from_station_code="ET", to_station_code="NGP",
         distance_km=245.0, scheduled_running_minutes=180, speed_limit_kmph=110, zone="WCR"),
    dict(section_code="NGP-CSMT", from_station_code="NGP", to_station_code="CSMT",
         distance_km=837.0, scheduled_running_minutes=600, speed_limit_kmph=120, zone="CR"),
]

# route: ordered station codes: every stop the train makes, so each consecutive pair
# always matches a seeded RailwaySection (see the Phase 2 data-integrity requirement).
TRAINS: list[dict] = [
    dict(train_number="12951", train_name="Mumbai Rajdhani Express", train_type=TrainType.RAJDHANI,
         zone="NR", priority=TrainPriority.HIGH, origin_departure=time(16, 25), halt_minutes=5,
         route=["NDLS", "MTJ", "AGC", "GWL", "JHS", "BPL", "ET", "NGP", "CSMT"]),
    dict(train_number="12002", train_name="Bhopal Shatabdi Express", train_type=TrainType.SHATABDI,
         zone="NR", priority=TrainPriority.HIGH, origin_departure=time(6, 15), halt_minutes=2,
         route=["NDLS", "MTJ", "AGC", "GWL", "JHS", "BPL"]),
    dict(train_number="12615", train_name="Grand Trunk Superfast Express", train_type=TrainType.SUPERFAST,
         zone="NR", priority=TrainPriority.NORMAL, origin_departure=time(18, 10), halt_minutes=5,
         route=["NDLS", "MTJ", "AGC", "GWL", "JHS", "BINA", "BPL", "ET", "NGP"]),
    dict(train_number="11077", train_name="Jhelum Superfast Express", train_type=TrainType.SUPERFAST,
         zone="CR", priority=TrainPriority.NORMAL, origin_departure=time(9, 0), halt_minutes=5,
         route=["AGC", "GWL", "JHS", "BPL", "ET"]),
    dict(train_number="14217", train_name="Prayagraj Express", train_type=TrainType.EXPRESS,
         zone="NR", priority=TrainPriority.NORMAL, origin_departure=time(20, 40), halt_minutes=5,
         route=["NDLS", "MTJ", "AGC"]),
    dict(train_number="12138", train_name="Punjab Mail", train_type=TrainType.EXPRESS,
         zone="CR", priority=TrainPriority.NORMAL, origin_departure=time(5, 0), halt_minutes=5,
         route=["NGP", "CSMT"]),
    dict(train_number="12294", train_name="Sanghamitra Superfast Express", train_type=TrainType.SUPERFAST,
         zone="WCR", priority=TrainPriority.NORMAL, origin_departure=time(11, 30), halt_minutes=5,
         route=["BPL", "ET", "NGP", "CSMT"]),
]

# Sample real-time-shaped events — clearly SIMULATOR-sourced, not live data.
EVENTS: list[dict] = [
    dict(train_number="12951", event_type=EventType.DEPARTURE, station_code="NDLS", section_code=None,
         delay_minutes=0, speed_kmph=0, minutes_ago=180),
    dict(train_number="12951", event_type=EventType.POSITION_UPDATE, station_code=None, section_code="MTJ-AGC",
         delay_minutes=12, speed_kmph=95, minutes_ago=90, latitude=27.30, longitude=77.85),
    dict(train_number="12951", event_type=EventType.SIGNAL_HALT, station_code=None, section_code="AGC-GWL",
         delay_minutes=15, speed_kmph=0, minutes_ago=60, metadata={"reason": "awaiting platform clearance"}),
    dict(train_number="12002", event_type=EventType.ARRIVAL, station_code="AGC", section_code=None,
         delay_minutes=3, speed_kmph=0, minutes_ago=45),
    dict(train_number="12615", event_type=EventType.CONGESTION, station_code=None, section_code="JHS-BINA",
         delay_minutes=20, speed_kmph=40, minutes_ago=30, metadata={"density": "high"}),
    dict(train_number="11077", event_type=EventType.SPEED_RESTRICTION, station_code=None, section_code="GWL-JHS",
         delay_minutes=8, speed_kmph=45, minutes_ago=20, metadata={"restriction_kmph": 45}),
]


def _average_running_minutes(scheduled_running_minutes: int) -> int:
    """Sample 'typical actual' running time: a bit above schedule, as real trains rarely
    beat their padded timetable. Purely illustrative until real historical data exists.
    """
    return scheduled_running_minutes + max(5, round(scheduled_running_minutes * 0.05))


async def seed_stations(session: AsyncSession) -> dict[str, Station]:
    by_code: dict[str, Station] = {}
    created = 0
    for data in STATIONS:
        existing = await station_repository.get_by_code(session, data["station_code"])
        if existing is not None:
            by_code[data["station_code"]] = existing
            continue
        station = await station_repository.create(session, StationCreate(**data))
        by_code[data["station_code"]] = station
        created += 1
    logger.info("Stations: %d created, %d already present", created, len(STATIONS) - created)
    return by_code


async def seed_sections(session: AsyncSession, stations: dict[str, Station]) -> dict[tuple[str, str], RailwaySection]:
    by_pair: dict[tuple[str, str], RailwaySection] = {}
    created = 0
    for data in SECTIONS:
        existing = await section_repository.get_by_code(session, data["section_code"])
        if existing is not None:
            by_pair[(data["from_station_code"], data["to_station_code"])] = existing
            continue
        section = await section_repository.create(
            session,
            RailwaySectionCreate(
                section_code=data["section_code"],
                from_station_id=stations[data["from_station_code"]].id,
                to_station_id=stations[data["to_station_code"]].id,
                distance_km=data["distance_km"],
                scheduled_running_minutes=data["scheduled_running_minutes"],
                average_running_minutes=_average_running_minutes(data["scheduled_running_minutes"]),
                speed_limit_kmph=data["speed_limit_kmph"],
                zone=data["zone"],
            ),
        )
        by_pair[(data["from_station_code"], data["to_station_code"])] = section
        created += 1
    logger.info("Railway sections: %d created, %d already present", created, len(SECTIONS) - created)
    return by_pair


def _build_route_entries(
    stations: dict[str, Station],
    sections_by_pair: dict[tuple[str, str], RailwaySection],
    station_codes: list[str],
    origin_departure: time,
    halt_minutes: int,
) -> list[dict]:
    """Walk a train's stop sequence, deriving arrival/departure clock times, day_offset
    and cumulative distance purely from the section data — the single source of truth
    for running times/distances (see module docstring re: TrainRoute's date-free design).
    """
    entries: list[dict] = []
    elapsed_minutes = origin_departure.hour * 60 + origin_departure.minute
    cumulative_distance = 0.0

    for i, code in enumerate(station_codes):
        is_origin = i == 0
        is_terminus = i == len(station_codes) - 1
        section_id: int | None = None

        if not is_origin:
            prev_code = station_codes[i - 1]
            section = sections_by_pair[(prev_code, code)]
            section_id = section.id
            elapsed_minutes += section.scheduled_running_minutes
            cumulative_distance += float(section.distance_km)
            arrival_day, arrival_minute = divmod(elapsed_minutes, 24 * 60)
            arrival = time(hour=arrival_minute // 60, minute=arrival_minute % 60)
        else:
            arrival = None
            arrival_day = elapsed_minutes // (24 * 60)

        if not is_terminus:
            if not is_origin:
                elapsed_minutes += halt_minutes
            departure_day, departure_minute = divmod(elapsed_minutes, 24 * 60)
            departure = time(hour=departure_minute // 60, minute=departure_minute % 60)
            day_offset = departure_day if is_origin else arrival_day
            stop_halt = 0 if is_origin else halt_minutes
        else:
            departure = None
            day_offset = arrival_day
            stop_halt = 0

        entries.append(
            {
                "station_code": code,
                "section_id": section_id,
                "sequence_number": i + 1,
                "scheduled_arrival": arrival,
                "scheduled_departure": departure,
                "day_offset": day_offset,
                "halt_minutes": stop_halt,
                "distance_from_origin_km": round(cumulative_distance, 2),
            }
        )

    return entries


async def seed_trains_and_routes(
    session: AsyncSession,
    stations: dict[str, Station],
    sections_by_pair: dict[tuple[str, str], RailwaySection],
) -> dict[str, Train]:
    by_number: dict[str, Train] = {}
    trains_created = 0
    routes_created = 0

    for data in TRAINS:
        existing = await train_repository.get_by_number(session, data["train_number"])
        if existing is not None:
            by_number[data["train_number"]] = existing
            continue

        route_codes = data["route"]
        train = await train_repository.create(
            session,
            TrainCreate(
                train_number=data["train_number"],
                train_name=data["train_name"],
                train_type=data["train_type"],
                source_station_id=stations[route_codes[0]].id,
                destination_station_id=stations[route_codes[-1]].id,
                zone=data["zone"],
                priority=data["priority"],
                active=True,
            ),
        )
        await session.flush()  # ensure train.id is available for route rows

        entries = _build_route_entries(
            stations, sections_by_pair, route_codes, data["origin_departure"], data["halt_minutes"]
        )
        route_creates = [
            TrainRouteCreate(
                train_id=train.id,
                station_id=stations[entry["station_code"]].id,
                section_id=entry["section_id"],
                sequence_number=entry["sequence_number"],
                scheduled_arrival=entry["scheduled_arrival"],
                scheduled_departure=entry["scheduled_departure"],
                day_offset=entry["day_offset"],
                halt_minutes=entry["halt_minutes"],
                distance_from_origin_km=entry["distance_from_origin_km"],
            )
            for entry in entries
        ]
        await route_repository.bulk_create(session, route_creates)

        by_number[data["train_number"]] = train
        trains_created += 1
        routes_created += len(route_creates)

    logger.info("Trains: %d created, %d already present", trains_created, len(TRAINS) - trains_created)
    logger.info("Train route entries created: %d", routes_created)
    return by_number


async def seed_events(session: AsyncSession, trains: dict[str, Train], stations: dict[str, Station],
                       sections_by_pair: dict[tuple[str, str], RailwaySection]) -> int:
    existing_count = (await session.execute(select(func.count()).select_from(TrainEvent))).scalar_one()
    if existing_count > 0:
        logger.info("Train events: %d already present, skipping sample event seeding", existing_count)
        return 0

    now = datetime.now(timezone.utc)
    section_by_code = {data["section_code"]: sections_by_pair[(data["from_station_code"], data["to_station_code"])]
                        for data in SECTIONS}

    created = 0
    for data in EVENTS:
        await event_repository.create(
            session,
            TrainEventCreate(
                train_id=trains[data["train_number"]].id,
                timestamp=now - timedelta(minutes=data["minutes_ago"]),
                latitude=data.get("latitude"),
                longitude=data.get("longitude"),
                speed_kmph=data.get("speed_kmph"),
                station_id=stations[data["station_code"]].id if data.get("station_code") else None,
                section_id=section_by_code[data["section_code"]].id if data.get("section_code") else None,
                delay_minutes=data["delay_minutes"],
                event_type=data["event_type"],
                event_source=EventSource.SIMULATOR,
                metadata=data.get("metadata"),
            ),
        )
        created += 1

    logger.info("Train events created: %d", created)
    return created


async def run_seed(reset: bool = False) -> None:
    from sqlalchemy import text

    async with AsyncSessionLocal() as session:
        if reset:
            await session.execute(text("DELETE FROM alerts"))
            await session.execute(text("DELETE FROM predictions"))
            await session.execute(text("DELETE FROM train_events"))
            await session.commit()

        stations = await seed_stations(session)
        sections_by_pair = await seed_sections(session, stations)
        trains = await seed_trains_and_routes(session, stations, sections_by_pair)
        await seed_events(session, trains, stations, sections_by_pair)
        await session.commit()
    logger.info("Seed complete.")


def main() -> None:
    import sys

    setup_logging()
    reset = "--reset" in sys.argv
    asyncio.run(run_seed(reset=reset))


if __name__ == "__main__":
    main()
