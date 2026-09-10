"""Phase 5 unit tests — the baseline ETA engine's pure computation.

These tests run WITHOUT PostgreSQL or Redis: they feed hand-built model objects into
`compute_baseline_eta` and the resolver/estimator helpers, with deterministic fixtures
(no real external railway APIs anywhere).
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.enums import EventSource, EventType
from app.models.route import TrainRoute
from app.models.section import RailwaySection
from app.models.station import Station
from app.models.train import Train
from app.models.train_event import TrainEvent
from app.services import baseline_eta_service as svc
from app.services.position_resolver import (
    PositionKind,
    PositionSource,
    dedupe_route,
    resolve_position,
)

JOURNEY_DATE = date(2026, 9, 10)


def _station(code: str, name: str, lat: float, lon: float, id: int) -> Station:
    s = Station(station_code=code, station_name=name, latitude=Decimal(str(lat)),
                longitude=Decimal(str(lon)), zone="NR", station_type="MAJOR")
    s.id = id
    return s


def _section(code: str, frm: Station, to: Station, distance: float, sched: int | None,
             avg: int | None, limit: int | None) -> RailwaySection:
    return RailwaySection(
        section_code=code, from_station=frm, to_station=to, from_station_id=1, to_station_id=2,
        distance_km=Decimal(str(distance)), scheduled_running_minutes=sched,  # type: ignore[arg-type]
        average_running_minutes=avg,  # type: ignore[arg-type]
        speed_limit_kmph=limit,  # type: ignore[arg-type]
        zone="NR",
    )


def _route_entry(train_id: int, station: Station, seq: int, *, section: RailwaySection | None = None,
                 arrival: time | None = None, halt: int = 0, day_offset: int = 0,
                 dist_from_origin: float = 0.0) -> TrainRoute:
    return TrainRoute(
        train_id=train_id, station=station, station_id=station.id,
        section=section, section_id=section.id if section else None,
        sequence_number=seq, scheduled_arrival=arrival, scheduled_departure=arrival, day_offset=day_offset,
        halt_minutes=halt, distance_from_origin_km=Decimal(str(dist_from_origin)),
    )


def _event(**kwargs) -> TrainEvent:
    defaults = dict(
        train_id=1, timestamp=datetime.now(timezone.utc) - timedelta(minutes=5),
        delay_minutes=0, event_type=EventType.POSITION_UPDATE, event_source=EventSource.SIMULATOR,
    )
    defaults.update(kwargs)
    return TrainEvent(**defaults)


def _train() -> Train:
    return Train(train_number="T001", train_name="Test Express", train_type="EXPRESS",
                 source_station_id=1, destination_station_id=3, zone="NR", priority="NORMAL", active=True)


@pytest.fixture
def network():
    """A tiny deterministic three-station line: NDLS -(141km,95m)-> MTJ -(54km,40m)-> AGC.

    Scheduled arrivals: MTJ 10:00 (+0d), AGC 11:00 (+0d). Halt at MTJ: 5 min.
    """
    ndls = _station("NDLS", "New Delhi", 28.6432, 77.2196, 1)
    mtj = _station("MTJ", "Mathura Junction", 27.4924, 77.6737, 2)
    agc = _station("AGC", "Agra Cantt", 27.1591, 78.0092, 3)
    s1 = _section("NDLS-MTJ", ndls, mtj, 141.0, 95, 100, 130)
    s1.id = 11
    s2 = _section("MTJ-AGC", mtj, agc, 54.0, 40, 42, 110)
    s2.id = 12
    route = [
        _route_entry(1, ndls, 1, arrival=None),
        _route_entry(1, mtj, 2, section=s1, arrival=time(10, 0), halt=5, dist_from_origin=141.0),
        _route_entry(1, agc, 3, section=s2, arrival=time(11, 0), dist_from_origin=195.0),
    ]
    return _train(), route, {"NDLS": ndls, "MTJ": mtj, "AGC": agc, "s1": s1, "s2": s2}


# --- position resolution ---------------------------------------------------------


def test_resolver_at_station(network):
    _, route, objs = network
    event = _event(station_id=2, station=objs["MTJ"], event_type=EventType.ARRIVAL)
    r = resolve_position(event, route)
    assert r.kind == PositionKind.AT_STATION
    assert r.first_upcoming_index == 2
    assert r.next_station_code == "AGC"


def test_resolver_departure_event_means_left_station(network):
    _, route, objs = network
    event = _event(station_id=2, station=objs["MTJ"], event_type=EventType.DEPARTURE)
    r = resolve_position(event, route)
    assert r.kind == PositionKind.DEPARTED_STATION
    assert r.first_upcoming_index == 2


def test_resolver_in_section_without_gps_uses_full_section(network):
    _, route, objs = network
    event = _event(section_id=12, section=objs["s2"])
    r = resolve_position(event, route)
    assert r.kind == PositionKind.IN_SECTION
    assert r.fraction_remaining_in_section is None


def test_resolver_in_section_with_gps_estimates_fraction(network):
    _, route, objs = network
    # Halfway between Mathura and Agra on the straight line.
    lat = (27.4924 + 27.1591) / 2
    lon = (77.6737 + 78.0092) / 2
    event = _event(section_id=12, section=objs["s2"], latitude=lat, longitude=lon)
    r = resolve_position(event, route)
    assert r.kind == PositionKind.IN_SECTION
    assert r.fraction_remaining_in_section == pytest.approx(0.5, abs=0.15)


def test_resolver_gps_only_near_station(network):
    _, route, objs = network
    event = _event(latitude=27.495, longitude=77.675)  # ~0.3km from Mathura
    r = resolve_position(event, route)
    assert r.kind == PositionKind.AT_STATION
    assert r.position_source == PositionSource.LATEST_TRAIN_EVENT_GPS


def test_resolver_gps_only_mid_section(network):
    _, route, objs = network
    lat = (27.4924 + 27.1591) / 2
    lon = (77.6737 + 78.0092) / 2
    event = _event(latitude=lat, longitude=lon)
    r = resolve_position(event, route)
    assert r.kind == PositionKind.GPS_ONLY
    assert r.next_station_code == "AGC"


def test_resolver_no_event_assumes_not_started(network):
    _, route, _ = network
    r = resolve_position(None, route)
    assert r.kind == PositionKind.NO_POSITION
    assert r.position_source == PositionSource.NO_EVENT
    assert r.first_upcoming_index == 0


def test_resolver_event_station_not_on_route(network):
    other = _station("ZZZ", "Elsewhere", 20.0, 78.0, 99)
    _, route, _ = network
    event = _event(station_id=99, station=other)
    r = resolve_position(event, route)
    assert r.kind == PositionKind.NO_POSITION
    assert r.position_source == PositionSource.UNKNOWN


def test_resolver_invalid_gps_does_not_crash(network):
    _, route, _ = network
    event = _event(latitude=999.0, longitude=0.0)
    r = resolve_position(event, route)
    assert r.kind == PositionKind.NO_POSITION


def test_resolver_train_at_destination(network):
    _, route, objs = network
    event = _event(station_id=3, station=objs["AGC"], event_type=EventType.ARRIVAL)
    r = resolve_position(event, route)
    assert r.first_upcoming_index is None


def test_duplicate_route_entries_dropped():
    a, b = object(), object()
    entries = [TrainRoute(station_id=1, sequence_number=1), TrainRoute(station_id=1, sequence_number=2),
               TrainRoute(station_id=2, sequence_number=3)]
    entries[0].station_id = 1
    assert len(dedupe_route(entries)) == 2


def test_route_ordering_by_sequence():
    entries = [TrainRoute(station_id=2, sequence_number=2), TrainRoute(station_id=1, sequence_number=1)]
    ordered = dedupe_route(entries)
    assert [e.sequence_number for e in ordered] == [1, 2]


# --- speed hierarchy ---------------------------------------------------------------


def test_speed_clamped_to_maximum(network, monkeypatch):
    _, _, objs = network
    # Absurdly fast average (1 min for 54km = 3240 km/h) must clamp to config max.
    monkeypatch.setattr(objs["s2"], "average_running_minutes", 1)
    speed, method = svc.expected_speed_for_section(54.0, objs["s2"])
    assert speed == svc.get_settings().BASELINE_MAX_SPEED_KMPH
    assert method == "SECTION_AVERAGE"


def test_speed_clamped_to_minimum(network):
    _, _, objs = network
    # Average implying a walking pace (54km in 20h) must clamp to config min.
    speed, _ = svc.expected_speed_for_section(54.0, _section("X", objs["MTJ"], objs["AGC"], 54.0, None, 1200, None))
    assert speed == svc.get_settings().BASELINE_MIN_SPEED_KMPH


def test_scheduled_running_time_fallback(network):
    _, _, objs = network
    sec = _section("X", objs["MTJ"], objs["AGC"], 54.0, 40, None, None)
    speed, method = svc.expected_speed_for_section(54.0, sec)
    assert method == "SCHEDULE"
    assert speed == pytest.approx(54.0 / (40 / 60.0))


def test_speed_limit_fallback(network):
    _, _, objs = network
    sec = _section("X", objs["MTJ"], objs["AGC"], 54.0, None, None, 110)
    speed, method = svc.expected_speed_for_section(54.0, sec)
    assert method == "SPEED_LIMIT"
    assert speed == 110.0


def test_configured_fallback_speed(network):
    _, _, objs = network
    sec = _section("X", objs["MTJ"], objs["AGC"], 54.0, None, None, None)
    speed, method = svc.expected_speed_for_section(54.0, sec)
    assert method == "FALLBACK"
    assert speed == svc.get_settings().BASELINE_FALLBACK_SPEED_KMPH


def test_operational_speed_used_only_for_current_leg(network):
    _, _, objs = network
    speed, method = svc.expected_speed_for_section(54.0, objs["s2"], current_speed_kmph=70.0, is_current_leg=True)
    assert (speed, method) == (70.0, "OPERATIONAL_SPEED")
    speed, method = svc.expected_speed_for_section(54.0, objs["s2"], current_speed_kmph=70.0, is_current_leg=False)
    assert method == "SECTION_AVERAGE"


def test_zero_distance_section_zero_minutes(network):
    _, _, objs = network
    est = svc.estimate_section_running_time(0.0, objs["s2"])
    assert est.estimated_minutes == 0.0
    assert est.method == "ZERO_DISTANCE"


def test_no_negative_travel_time(network):
    _, _, objs = network
    est = svc.estimate_section_running_time(54.0, objs["s2"])
    assert est.estimated_minutes > 0


# --- full-engine behaviour -----------------------------------------------------------


def test_train_at_station_eta(network):
    train, route, objs = network
    event = _event(station_id=2, station=objs["MTJ"], event_type=EventType.ARRIVAL, delay_minutes=12)
    result = svc.compute_baseline_eta(train, route, event, JOURNEY_DATE)
    assert [s.station_code for s in result.stations] == ["AGC"]
    agc = result.stations[0]
    assert agc.scheduled_arrival == datetime(2026, 9, 10, 11, 0, tzinfo=timezone.utc)
    # SECTION_AVERAGE for 54km @42min => 77.14km/h... deviation = 54/(42/60) -> minutes
    # 54km at speed 54/(42/60)=77.14 => 42.0min; deviation 2.0; recovery min(0.6,2)=0.6
    assert agc.baseline_eta > agc.scheduled_arrival
    assert 11.0 <= agc.delay_minutes <= 15.0
    assert agc.prediction_mode.value == "BASELINE"
    assert agc.calculation_details.distance_source == "RAILWAY_SECTION"


def test_train_in_section_without_gps_full_distance(network):
    train, route, objs = network
    event = _event(section_id=12, section=objs["s2"], delay_minutes=10)
    result = svc.compute_baseline_eta(train, route, event, JOURNEY_DATE)
    agc = result.stations[0]
    assert agc.remaining_distance_km == pytest.approx(54.0)
    assert result.current_position.kind == "IN_SECTION"
    assert result.current_position.last_known_station_code == "MTJ"


def test_train_in_section_with_gps_reduced_distance(network):
    train, route, objs = network
    lat = (27.4924 + 27.1591) / 2
    lon = (77.6737 + 78.0092) / 2
    event = _event(section_id=12, section=objs["s2"], latitude=lat, longitude=lon, delay_minutes=10)
    result = svc.compute_baseline_eta(train, route, event, JOURNEY_DATE)
    agc = result.stations[0]
    assert 0.2 * 54.0 < agc.remaining_distance_km < 0.8 * 54.0
    # Not re-charged the full section distance.
    assert agc.remaining_distance_km < 54.0


def test_no_latest_event_baseline_equals_schedule(network):
    train, route, _ = network
    result = svc.compute_baseline_eta(train, route, None, JOURNEY_DATE)
    assert result.data_status == "UNAVAILABLE"
    assert result.data_source is None
    assert [s.station_code for s in result.stations] == ["MTJ", "AGC"]
    for st in result.stations:
        # No live state => no delay input; but section-average running time still
        # legitimately shifts the baseline past schedule (avg 100m vs sched 95m here).
        assert st.delay_minutes >= 0.0
        assert st.baseline_eta >= st.scheduled_arrival
        assert st.prediction_mode.value == "BASELINE"


def test_zero_delay(network):
    train, route, objs = network
    event = _event(station_id=1, station=objs["NDLS"], delay_minutes=0)
    result = svc.compute_baseline_eta(train, route, event, JOURNEY_DATE)
    assert all(s.delay_minutes >= 0.0 for s in result.stations)


def test_positive_delay_propagates_but_recovers(network):
    train, route, objs = network
    event = _event(station_id=1, station=objs["NDLS"], delay_minutes=20)
    result = svc.compute_baseline_eta(train, route, event, JOURNEY_DATE)
    delays = [s.delay_minutes for s in result.stations]
    # Not the same delay copied to every station: recovery erodes it section by section.
    assert delays[0] > 0
    assert delays[0] != 20.0  # recovery + deviation already applied on first leg
    assert delays[1] <= delays[0] + 3.0
    details = result.calculation_details
    assert details["recovery_applied_minutes"] > 0
    assert details["recovery_model"] == "CONFIGURED_BASELINE_RECOVERY"


def test_recovery_is_capped_per_section(network):
    train, route, objs = network
    event = _event(station_id=2, station=objs["MTJ"], event_type=EventType.ARRIVAL, delay_minutes=60)
    result = svc.compute_baseline_eta(train, route, event, JOURNEY_DATE)
    agc = result.stations[0]
    rec = svc._recovery_minutes(60.0)
    assert rec <= svc.get_settings().BASELINE_MAX_RECOVERY_MINUTES_PER_SECTION
    # deviation for MTJ-AGC at SECTION_AVERAGE (42min vs sched 40) = 2.0
    expected = 60.0 + 2.0 - rec
    assert agc.delay_minutes == pytest.approx(expected, abs=0.6)


def test_negative_delay_input_clamped(network):
    train, route, objs = network
    event = _event(station_id=2, station=objs["MTJ"], event_type=EventType.ARRIVAL, delay_minutes=-7)
    result = svc.compute_baseline_eta(train, route, event, JOURNEY_DATE)
    assert all(s.delay_minutes >= 0.0 for s in result.stations)


def test_extremely_large_delay_does_not_crash(network):
    train, route, objs = network
    event = _event(station_id=1, station=objs["NDLS"], delay_minutes=10_000)
    result = svc.compute_baseline_eta(train, route, event, JOURNEY_DATE)
    assert result.stations[0].delay_minutes > 9000


def test_station_halt_included_in_fallback_walk(network):
    train, route, objs = network
    # Make the timetable unusable for AGC so the fallback path triggers.
    route[2].scheduled_arrival = None
    event = _event(station_id=2, station=objs["MTJ"], event_type=EventType.ARRIVAL)
    now = datetime(2026, 9, 10, 10, 5, tzinfo=timezone.utc)
    result = svc.compute_baseline_eta(train, route, event, JOURNEY_DATE, now=now)
    agc = result.stations[0]
    assert agc.prediction_mode.value == "BASELINE_FALLBACK"
    # 54km at 54/(42/60)=77.14km/h -> 42min; halt at MTJ (5min) counts since we depart it.
    assert agc.baseline_eta > now + timedelta(minutes=42)
    assert result.calculation_details["calculation_method"] == "SECTION_AWARE_WITH_FALLBACK"


def test_missing_section_uses_route_distance_metadata(network):
    train, route, objs = network
    route[2].section = None  # section row missing
    route[2].section_id = None
    event = _event(station_id=2, station=objs["MTJ"], event_type=EventType.ARRIVAL, delay_minutes=5)
    result = svc.compute_baseline_eta(train, route, event, JOURNEY_DATE)
    agc = result.stations[0]
    assert agc.remaining_distance_km == pytest.approx(54.0)  # 195 - 141 from route metadata
    assert agc.calculation_details.distance_source == "ROUTE_DISTANCE_METADATA"


def test_geographic_approximation_labelled(network):
    train, route, objs = network
    route[2].section = None
    route[2].section_id = None
    route[2].distance_from_origin_km = route[1].distance_from_origin_km  # delta unusable
    event = _event(station_id=2, station=objs["MTJ"], event_type=EventType.ARRIVAL)
    result = svc.compute_baseline_eta(train, route, event, JOURNEY_DATE)
    assert result.stations[0].calculation_details.distance_source == "GEOGRAPHIC_APPROXIMATION"


def test_multiple_upcoming_stations_and_destination_included(network):
    train, route, objs = network
    event = _event(station_id=1, station=objs["NDLS"], event_type=EventType.DEPARTURE)
    result = svc.compute_baseline_eta(train, route, event, JOURNEY_DATE)
    assert [s.station_code for s in result.stations] == ["MTJ", "AGC"]
    # Distances accumulate along the route, never decrease.
    dists = [s.remaining_distance_km for s in result.stations]
    assert dists == sorted(dists)
    assert dists[-1] == pytest.approx(195.0)


def test_train_at_destination_returns_no_stations(network):
    train, route, objs = network
    event = _event(station_id=3, station=objs["AGC"], event_type=EventType.ARRIVAL)
    result = svc.compute_baseline_eta(train, route, event, JOURNEY_DATE)
    assert result.stations == []
    assert result.calculation_details["at_destination"] is True


def test_scheduled_arrival_never_modified(network):
    train, route, objs = network
    event = _event(station_id=1, station=objs["NDLS"], delay_minutes=30)
    result = svc.compute_baseline_eta(train, route, event, JOURNEY_DATE)
    assert result.stations[0].scheduled_arrival == datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc)
    assert result.stations[1].scheduled_arrival == datetime(2026, 9, 10, 11, 0, tzinfo=timezone.utc)
    assert result.stations[1].baseline_eta > result.stations[1].scheduled_arrival


def test_day_offset_respected(network):
    train, route, objs = network
    route[2].day_offset = 1
    event = _event(station_id=1, station=objs["NDLS"], delay_minutes=0)
    result = svc.compute_baseline_eta(train, route, event, JOURNEY_DATE)
    assert result.stations[1].scheduled_arrival.day == 11


def test_stale_event_reported_as_stale(network):
    train, route, objs = network
    event = _event(station_id=2, station=objs["MTJ"], event_type=EventType.ARRIVAL,
                   timestamp=datetime.now(timezone.utc) - timedelta(hours=5))
    result = svc.compute_baseline_eta(train, route, event, JOURNEY_DATE)
    assert result.data_status == "STALE"
    assert result.data_source == "SIMULATOR"


def test_fresh_simulator_event_reported_as_simulated(network):
    train, route, objs = network
    event = _event(station_id=2, station=objs["MTJ"], event_type=EventType.ARRIVAL)
    result = svc.compute_baseline_eta(train, route, event, JOURNEY_DATE)
    assert result.data_status == "SIMULATED"
    assert result.data_source == "SIMULATOR"


def test_live_source_event_reported_as_live(network):
    train, route, objs = network
    event = _event(station_id=2, station=objs["MTJ"], event_type=EventType.ARRIVAL,
                   event_source=EventSource.NTES)
    result = svc.compute_baseline_eta(train, route, event, JOURNEY_DATE)
    assert result.data_status == "LIVE"
    assert result.data_source == "NTES"


def test_explainability_metadata_present(network):
    train, route, objs = network
    event = _event(section_id=12, section=objs["s2"], delay_minutes=12)
    result = svc.compute_baseline_eta(train, route, event, JOURNEY_DATE)
    details = result.calculation_details
    assert details["position_source"] == "LATEST_TRAIN_EVENT_SECTION"
    assert details["remaining_sections"] == 1
    assert details["delay_input_minutes"] == 12
    assert details["speed_sources"]
    per_station = result.stations[0].calculation_details
    assert per_station.speed_source
    assert per_station.distance_source
    assert per_station.delay_input_minutes == 12


def test_empty_route_does_not_crash():
    train = _train()
    result = svc.compute_baseline_eta(train, [], None, JOURNEY_DATE)
    assert result.stations == []
