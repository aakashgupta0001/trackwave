"""Top-level network-intelligence orchestration (modules 19-21): the two entry points
`analyze_train_impact` and `analyze_network` that everything else (API routes, alerts)
builds on. Ties together graph.py (candidate discovery), resolver.py (occupancy
windows), conflict.py (shared-section overlap), propagation.py (delay propagation), and
scoring.py (impact scores/severity) — reusing the Phase 5/6/7 ETA engine for the source
train's own timing rather than recomputing it (modules 30, 31).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.enums import AlertSeverity, AlertType
from app.network import graph
from app.network.conflict import detect_section_conflicts
from app.network.propagation import DeterministicPropagationModel
from app.network.resolver import build_schedule_windows, build_source_windows
from app.network.schemas import (
    AffectedTrain,
    ImpactSeverity,
    NetworkAnalysisStatus,
    NetworkConflict,
    NetworkHotspot,
    NetworkOverviewResponse,
    SectionImpact,
    StationImpact,
    TimelineBucket,
    TrainImpactResponse,
)
from app.network.scoring import hotspot_score, severity_for_score, train_impact_score
from app.services import baseline_eta_service, eta_fusion_service
from app.services.exceptions import NotFoundError

logger = logging.getLogger(__name__)

_propagation_model = DeterministicPropagationModel()


async def _empty_impact_response(
    train_number: str, train_name: str, source_delay: float, status: NetworkAnalysisStatus, notes: list[str]
) -> TrainImpactResponse:
    settings = get_settings()
    return TrainImpactResponse(
        train_number=train_number,
        train_name=train_name,
        analysis_status=status,
        source_delay_minutes=round(source_delay, 1),
        network_impact_score=0,
        severity=ImpactSeverity.LOW,
        affected_trains=[],
        affected_stations=[],
        affected_sections=[],
        conflicts=[],
        generated_at=datetime.now(timezone.utc),
        horizon_minutes=settings.NETWORK_ANALYSIS_HORIZON_MINUTES,
        notes=notes,
    )


async def analyze_train_impact(
    session: AsyncSession, train_number: str, journey_date: date | None = None
) -> TrainImpactResponse:
    """Predicted network impact of one train's current delay. Never raises for "no
    delay" or "insufficient data" — those are legitimate, well-formed zero-impact
    results (modules 36, 37), not errors. Raises NotFoundError only if the train itself
    doesn't exist.
    """
    settings = get_settings()
    train, route, latest_event = await baseline_eta_service.load_engine_inputs(session, train_number)
    source_delay = float(latest_event.delay_minutes) if latest_event is not None else 0.0

    if not route:
        return await _empty_impact_response(
            train.train_number, train.train_name, source_delay, NetworkAnalysisStatus.LIMITED,
            ["Network impact analysis is limited because route/section data is incomplete."],
        )
    if source_delay <= 0:
        return await _empty_impact_response(
            train.train_number, train.train_name, source_delay, NetworkAnalysisStatus.OK,
            ["Train has no currently known delay — nothing to propagate."],
        )

    final_eta_response = await eta_fusion_service.get_final_eta(
        session, train_number, journey_date, include_explanations=False
    )
    source_windows = build_source_windows(
        route, final_eta_response, latest_event.timestamp if latest_event is not None else None
    )
    if not source_windows:
        return await _empty_impact_response(
            train.train_number, train.train_name, source_delay, NetworkAnalysisStatus.LIMITED,
            ["Network impact analysis is limited because no upcoming section could be resolved for this train."],
        )

    visited_train_ids = {train.id}
    frontier: list[tuple] = [(train, route, source_windows, source_delay, 0)]
    affected_by_number: dict[str, AffectedTrain] = {}
    all_conflicts: list[NetworkConflict] = []
    max_overlap_seen = 0.0
    max_depth_reached = 0

    while frontier:
        next_frontier: list[tuple] = []
        for cur_train, cur_route, cur_windows, cur_delay, depth in frontier:
            if depth > settings.NETWORK_MAX_PROPAGATION_DEPTH:
                continue
            section_ids = list(cur_windows.keys())
            candidates = await graph.find_candidate_trains(
                session,
                section_ids=section_ids,
                exclude_train_ids=visited_train_ids,
                limit=settings.NETWORK_MAX_TRAINS_PER_ANALYSIS,
            )
            for candidate in candidates:
                if candidate.id in visited_train_ids:
                    continue
                cand_train, cand_route, cand_event = await baseline_eta_service.load_engine_inputs(
                    session, candidate.train_number
                )
                cand_own_delay = float(cand_event.delay_minutes) if cand_event is not None else 0.0
                cand_windows = build_schedule_windows(cand_route, journey_date or date.today(), cand_own_delay)

                conflicts = detect_section_conflicts(
                    cur_train.train_number, cand_train.train_number, cur_route, cand_route, cur_windows, cand_windows
                )
                if not conflicts:
                    continue

                strongest_result = None
                strongest_conflict = None
                for conflict in conflicts:
                    all_conflicts.append(conflict)
                    max_overlap_seen = max(max_overlap_seen, conflict.estimated_overlap_minutes or 0.0)
                    result = _propagation_model.propagate(
                        source_delay_minutes=cur_delay,
                        overlap_minutes=conflict.estimated_overlap_minutes or 0.0,
                        separation_minutes=conflict.separation_minutes or 0.0,
                        depth=depth,
                    )
                    if result is not None and (strongest_result is None or result.estimated_delay_minutes > strongest_result.estimated_delay_minutes):
                        strongest_result = result
                        strongest_conflict = conflict

                if strongest_result is None or strongest_conflict is None:
                    continue

                max_depth_reached = max(max_depth_reached, depth)
                existing = affected_by_number.get(cand_train.train_number)
                if existing is None or strongest_result.estimated_delay_minutes > existing.estimated_delay_minutes:
                    affected_by_number[cand_train.train_number] = AffectedTrain(
                        source_train_number=train.train_number,
                        train_number=cand_train.train_number,
                        train_name=cand_train.train_name,
                        section_code=strongest_conflict.section_code,
                        station_code=strongest_conflict.station_code,
                        estimated_delay_minutes=strongest_result.estimated_delay_minutes,
                        propagation_depth=depth,
                        impact_severity=strongest_conflict.severity,
                        impact_confidence=strongest_result.confidence,
                        reason=strongest_conflict.reason,
                    )

                visited_train_ids.add(candidate.id)
                if depth < settings.NETWORK_MAX_PROPAGATION_DEPTH:
                    next_windows = build_schedule_windows(
                        cand_route, journey_date or date.today(), strongest_result.estimated_delay_minutes
                    )
                    next_frontier.append(
                        (cand_train, cand_route, next_windows, strongest_result.estimated_delay_minutes, depth + 1)
                    )
        frontier = next_frontier

    affected_trains = sorted(affected_by_number.values(), key=lambda a: -a.estimated_delay_minutes)

    affected_sections = _aggregate_sections(all_conflicts, affected_trains)
    affected_stations = await _aggregate_stations(session, all_conflicts, affected_trains)

    score = train_impact_score(
        source_delay_minutes=source_delay,
        affected_train_count=len(affected_trains),
        affected_section_count=len(affected_sections),
        affected_station_count=len(affected_stations),
        max_overlap_minutes=max_overlap_seen,
        max_propagation_depth=max_depth_reached,
    )
    severity = severity_for_score(score)

    response = TrainImpactResponse(
        train_number=train.train_number,
        train_name=train.train_name,
        analysis_status=NetworkAnalysisStatus.OK,
        source_delay_minutes=round(source_delay, 1),
        network_impact_score=score,
        severity=severity,
        affected_trains=affected_trains,
        affected_stations=affected_stations,
        affected_sections=affected_sections,
        conflicts=all_conflicts,
        generated_at=datetime.now(timezone.utc),
        horizon_minutes=settings.NETWORK_ANALYSIS_HORIZON_MINUTES,
    )

    if score >= settings.NETWORK_ALERT_THRESHOLD:
        await _create_predictive_alerts(session, train, response)

    return response


def _aggregate_sections(conflicts: list[NetworkConflict], affected_trains: list[AffectedTrain]) -> list[SectionImpact]:
    by_section: dict[str, dict] = {}
    for conflict in conflicts:
        if conflict.section_code is None:
            continue
        bucket = by_section.setdefault(
            conflict.section_code,
            {"trains": set(), "conflict_count": 0, "max_delay": 0.0},
        )
        bucket["trains"].add(conflict.train_a)
        bucket["trains"].add(conflict.train_b)
        bucket["conflict_count"] += 1

    for affected in affected_trains:
        if affected.section_code is None or affected.section_code not in by_section:
            continue
        by_section[affected.section_code]["max_delay"] = max(
            by_section[affected.section_code]["max_delay"], affected.estimated_delay_minutes
        )

    results = []
    for conflict in conflicts:
        if conflict.section_code is None or conflict.section_code in {r.section_code for r in results}:
            continue
        bucket = by_section[conflict.section_code]
        score = hotspot_score(
            affected_train_count=len(bucket["trains"]), conflict_count=bucket["conflict_count"],
            total_estimated_delay=bucket["max_delay"],
        )
        # from/to station codes: any conflict referencing this section carries it via the
        # underlying window, but NetworkConflict doesn't store from_station — parse from
        # the section code convention (FROM-TO) used throughout the seed network as a
        # display fallback; exact station codes are resolved in _aggregate_stations.
        parts = conflict.section_code.split("-", 1)
        results.append(
            SectionImpact(
                section_code=conflict.section_code,
                from_station_code=parts[0] if parts else "",
                to_station_code=parts[1] if len(parts) > 1 else "",
                affected_trains=len(bucket["trains"]),
                estimated_delay_minutes=round(bucket["max_delay"], 1),
                conflict_count=bucket["conflict_count"],
                severity=severity_for_score(score),
            )
        )
    return results


async def _aggregate_stations(
    session: AsyncSession, conflicts: list[NetworkConflict], affected_trains: list[AffectedTrain]
) -> list[StationImpact]:
    from app.repositories import station_repository

    by_station: dict[str, dict] = {}
    for conflict in conflicts:
        if conflict.station_code is None:
            continue
        bucket = by_station.setdefault(conflict.station_code, {"trains": set(), "max_delay": 0.0})
        bucket["trains"].add(conflict.train_a)
        bucket["trains"].add(conflict.train_b)
    for affected in affected_trains:
        if affected.station_code is None:
            continue
        bucket = by_station.setdefault(affected.station_code, {"trains": set(), "max_delay": 0.0})
        bucket["trains"].add(affected.train_number)
        bucket["max_delay"] = max(bucket["max_delay"], affected.estimated_delay_minutes)

    results = []
    for code, bucket in by_station.items():
        station = await station_repository.get_by_code(session, code)
        if station is None:
            continue
        score = hotspot_score(affected_train_count=len(bucket["trains"]), conflict_count=0, total_estimated_delay=bucket["max_delay"])
        results.append(
            StationImpact(
                station_code=station.station_code,
                station_name=station.station_name,
                affected_train_count=len(bucket["trains"]),
                estimated_delay_minutes=round(bucket["max_delay"], 1),
                severity=severity_for_score(score),
                latitude=float(station.latitude),
                longitude=float(station.longitude),
            )
        )
    return results


async def _create_predictive_alerts(session: AsyncSession, train, response: TrainImpactResponse) -> None:
    """Only for genuinely significant impacts (module 26), deduplicated by a stable
    fingerprint so repeated analysis cycles never spam duplicate alerts (module 27).
    """
    from app.repositories import alert_repository

    time_bucket = datetime.now(timezone.utc).strftime("%Y%m%dT%H")  # hourly bucket

    # The train-level alert and each conflict-level alert are deduplicated
    # independently (each has its own fingerprint) — a duplicate train-level alert
    # must NOT skip checking/creating conflict-level alerts, since a later analysis
    # cycle can surface a genuinely new conflict for a train already alerted on.
    fingerprint = f"HIGH_NETWORK_IMPACT:{train.train_number}:{time_bucket}"
    if await alert_repository.find_by_fingerprint(session, fingerprint) is None:
        severity = (
            AlertSeverity.CRITICAL if response.severity == ImpactSeverity.CRITICAL else AlertSeverity.WARNING
        )
        await alert_repository.create(
            session,
            alert_type=AlertType.HIGH_NETWORK_IMPACT,
            severity=severity,
            title=f"Train {train.train_number} has predicted network-wide impact",
            description=(
                f"Train {train.train_number} ({train.train_name}) is running approximately "
                f"{round(response.source_delay_minutes)} min late. RAILCAST estimates this may affect "
                f"{len(response.affected_trains)} other train(s) — network impact score "
                f"{response.network_impact_score}/100 ({response.severity.value}). This is a predictive "
                "estimate, not a confirmed operational impact."
            ),
            train_id=train.id,
            metadata={
                "fingerprint": fingerprint,
                "network_impact_score": response.network_impact_score,
                "affected_train_count": len(response.affected_trains),
                "affected_trains": [a.train_number for a in response.affected_trains],
            },
        )
        await session.commit()

    for conflict in response.conflicts:
        if conflict.severity not in (ImpactSeverity.HIGH, ImpactSeverity.CRITICAL):
            continue
        conflict_fingerprint = (
            f"NETWORK_CONFLICT:{conflict.train_a}:{conflict.train_b}:{conflict.section_code}:{time_bucket}"
        )
        if await alert_repository.find_by_fingerprint(session, conflict_fingerprint) is not None:
            continue
        section = None
        if conflict.section_code:
            from app.repositories import section_repository

            section = await section_repository.get_by_code(session, conflict.section_code)
        await alert_repository.create(
            session,
            alert_type=AlertType.NETWORK_CONFLICT,
            severity=AlertSeverity.CRITICAL if conflict.severity == ImpactSeverity.CRITICAL else AlertSeverity.WARNING,
            title=f"Potential conflict: train {conflict.train_a} and train {conflict.train_b}",
            description=conflict.reason.description,
            section_id=section.id if section is not None else None,
            metadata={
                "fingerprint": conflict_fingerprint,
                "conflict_type": conflict.conflict_type.value,
                "train_a": conflict.train_a,
                "train_b": conflict.train_b,
                "section_code": conflict.section_code,
                "estimated_overlap_minutes": conflict.estimated_overlap_minutes,
            },
        )
        await session.commit()


async def _run_network_analysis(
    session: AsyncSession, journey_date: date | None = None
) -> tuple[NetworkOverviewResponse, list[TrainImpactResponse]]:
    """The actual network-wide walk (module 19): every currently-delayed active train is
    used as a propagation source, and the results are aggregated. Bounded by
    NETWORK_MAX_TRAINS_PER_ANALYSIS (module 34) — never an unbounded scan. Returns both
    the public overview AND the raw per-train results, so the other read endpoints
    (affected-trains, conflicts, hotspots, timeline) can derive their own views without
    re-running the analysis — see `get_network_snapshot` for the cached, shared entry
    point every API route actually calls.
    """
    from app.repositories import train_repository

    settings = get_settings()
    all_active = await train_repository.list_all(session, active_only=True)
    delayed_trains = await graph.find_delayed_trains(
        session, min_delay_minutes=1.0, limit=settings.NETWORK_MAX_TRAINS_PER_ANALYSIS
    )

    per_train_results: list[TrainImpactResponse] = []
    for train in delayed_trains:
        try:
            result = await analyze_train_impact(session, train.train_number, journey_date)
            per_train_results.append(result)
        except NotFoundError:
            continue

    affected_train_numbers: set[str] = set()
    affected_station_codes: set[str] = set()
    affected_section_codes: set[str] = set()
    all_conflicts_seen: set[tuple] = set()
    active_conflict_count = 0
    station_hotspot_data: dict[str, dict] = {}
    section_hotspot_data: dict[str, dict] = {}
    max_score = 0
    any_limited = False

    for result in per_train_results:
        if result.analysis_status == NetworkAnalysisStatus.LIMITED:
            any_limited = True
        max_score = max(max_score, result.network_impact_score)
        for affected in result.affected_trains:
            affected_train_numbers.add(affected.train_number)
        for station in result.affected_stations:
            affected_station_codes.add(station.station_code)
            bucket = station_hotspot_data.setdefault(
                station.station_code, {"name": station.station_name, "trains": set(), "conflicts": 0, "delay": 0.0}
            )
            bucket["trains"].add(result.train_number)
            bucket["delay"] = max(bucket["delay"], station.estimated_delay_minutes)
        for section in result.affected_sections:
            affected_section_codes.add(section.section_code)
            bucket = section_hotspot_data.setdefault(
                section.section_code,
                {"name": f"{section.from_station_code}-{section.to_station_code}", "trains": set(), "conflicts": 0, "delay": 0.0},
            )
            bucket["trains"].add(result.train_number)
            bucket["conflicts"] += section.conflict_count
            bucket["delay"] = max(bucket["delay"], section.estimated_delay_minutes)
        for conflict in result.conflicts:
            key = (conflict.conflict_type.value, conflict.train_a, conflict.train_b, conflict.section_code)
            if key not in all_conflicts_seen:
                all_conflicts_seen.add(key)
                active_conflict_count += 1

    hotspots: list[NetworkHotspot] = []
    for code, data in station_hotspot_data.items():
        score = hotspot_score(affected_train_count=len(data["trains"]), conflict_count=data["conflicts"], total_estimated_delay=data["delay"])
        hotspots.append(
            NetworkHotspot(
                entity_type="STATION", entity_code=code, entity_name=data["name"],
                affected_trains=len(data["trains"]), conflict_count=data["conflicts"],
                impact_score=score, severity=severity_for_score(score),
            )
        )
    for code, data in section_hotspot_data.items():
        score = hotspot_score(affected_train_count=len(data["trains"]), conflict_count=data["conflicts"], total_estimated_delay=data["delay"])
        hotspots.append(
            NetworkHotspot(
                entity_type="SECTION", entity_code=code, entity_name=data["name"],
                affected_trains=len(data["trains"]), conflict_count=data["conflicts"],
                impact_score=score, severity=severity_for_score(score),
            )
        )
    hotspots.sort(key=lambda h: -h.impact_score)

    overview = NetworkOverviewResponse(
        generated_at=datetime.now(timezone.utc),
        analysis_status=NetworkAnalysisStatus.LIMITED if any_limited else NetworkAnalysisStatus.OK,
        total_trains_monitored=len(all_active),
        delayed_trains=len(delayed_trains),
        affected_trains=len(affected_train_numbers),
        affected_stations=len(affected_station_codes),
        affected_sections=len(affected_section_codes),
        active_conflicts=active_conflict_count,
        hotspots=hotspots[:20],
        network_impact_score=max_score,
        severity=severity_for_score(max_score),
        horizon_minutes=settings.NETWORK_ANALYSIS_HORIZON_MINUTES,
        notes=(
            ["Some trains had incomplete route/section data; their contribution to this overview is partial."]
            if any_limited
            else []
        ),
    )
    return overview, per_train_results


_SNAPSHOT_CACHE_TTL_SECONDS = 20


async def get_network_snapshot(
    session: AsyncSession, journey_date: date | None = None, *, use_cache: bool = True
) -> tuple[NetworkOverviewResponse, list[TrainImpactResponse]]:
    """Cached entry point shared by every `/network/*` read endpoint (module 32): a
    short-TTL Redis cache means a burst of dashboard requests (overview + affected-trains
    + conflicts + hotspots + timeline, fired together by a frontend page load) triggers
    one graph analysis, not five.
    """
    import json

    from app.cache.redis import redis_client

    key = f"railcast:network:snapshot:{(journey_date or date.today()).isoformat()}"
    if use_cache:
        try:
            raw = await redis_client.get(key)
            if raw:
                payload = json.loads(raw)
                overview = NetworkOverviewResponse.model_validate(payload["overview"])
                per_train = [TrainImpactResponse.model_validate(p) for p in payload["per_train"]]
                return overview, per_train
        except Exception:
            logger.warning("Redis unavailable reading network snapshot cache key=%s", key, exc_info=True)

    overview, per_train_results = await _run_network_analysis(session, journey_date)

    try:
        payload = {
            "overview": overview.model_dump(mode="json"),
            "per_train": [p.model_dump(mode="json") for p in per_train_results],
        }
        await redis_client.set(key, json.dumps(payload), ex=_SNAPSHOT_CACHE_TTL_SECONDS)
    except Exception:
        logger.warning("Redis unavailable writing network snapshot cache key=%s", key, exc_info=True)

    return overview, per_train_results


async def analyze_network(session: AsyncSession, journey_date: date | None = None) -> NetworkOverviewResponse:
    """Public network-wide overview (module 19/21) — see `get_network_snapshot`."""
    overview, _ = await get_network_snapshot(session, journey_date)
    return overview


async def list_affected_trains(
    session: AsyncSession, journey_date: date | None = None
) -> list[AffectedTrain]:
    """Flat, deduplicated (strongest estimate wins) list of predicted-affected trains
    across every currently-delayed source train — backs GET /network/affected-trains.
    """
    _, per_train_results = await get_network_snapshot(session, journey_date)
    best: dict[str, AffectedTrain] = {}
    for result in per_train_results:
        for affected in result.affected_trains:
            existing = best.get(affected.train_number)
            if existing is None or affected.estimated_delay_minutes > existing.estimated_delay_minutes:
                best[affected.train_number] = affected
    return sorted(best.values(), key=lambda a: -a.estimated_delay_minutes)


async def list_conflicts(session: AsyncSession, journey_date: date | None = None) -> list[NetworkConflict]:
    """Flat, deduplicated list of predicted conflicts across every currently-delayed
    source train — backs GET /network/conflicts.
    """
    _, per_train_results = await get_network_snapshot(session, journey_date)
    seen: set[tuple] = set()
    conflicts: list[NetworkConflict] = []
    for result in per_train_results:
        for conflict in result.conflicts:
            key = (conflict.conflict_type.value, conflict.train_a, conflict.train_b, conflict.section_code)
            if key in seen:
                continue
            seen.add(key)
            conflicts.append(conflict)
    conflicts.sort(key=lambda c: -(c.estimated_overlap_minutes or 0.0))
    return conflicts


async def list_hotspots(session: AsyncSession, journey_date: date | None = None) -> list[NetworkHotspot]:
    """Backs GET /network/hotspots — the overview's own hotspot list."""
    overview, _ = await get_network_snapshot(session, journey_date)
    return overview.hotspots


async def get_timeline(
    session: AsyncSession, journey_date: date | None = None, *, bucket_minutes: int = 30
) -> list[TimelineBucket]:
    """Time-bucketed predicted network impact across the analysis horizon (module 25):
    for each bucket, how many predicted-affected trains and conflicts fall within it,
    and a bucket-local impact score. This is forward-looking (bucketed by when each
    conflict's estimated overlap window begins), not a historical trend — RAILCAST
    doesn't store a time series of past impact scores.
    """
    settings = get_settings()
    _, per_train_results = await get_network_snapshot(session, journey_date)
    now = datetime.now(timezone.utc)
    horizon = settings.NETWORK_ANALYSIS_HORIZON_MINUTES
    bucket_count = max(1, -(-horizon // bucket_minutes))

    buckets: list[dict] = [
        {"trains": set(), "conflicts": 0, "score": 0} for _ in range(bucket_count)
    ]

    for result in per_train_results:
        for conflict in result.conflicts:
            if conflict.predicted_at is None:
                continue
            offset_minutes = (conflict.predicted_at - now).total_seconds() / 60.0
            if offset_minutes < 0 or offset_minutes >= horizon:
                continue
            idx = min(bucket_count - 1, int(offset_minutes // bucket_minutes))
            buckets[idx]["trains"].add(conflict.train_a)
            buckets[idx]["trains"].add(conflict.train_b)
            buckets[idx]["conflicts"] += 1
            buckets[idx]["score"] = max(
                buckets[idx]["score"],
                hotspot_score(affected_train_count=len(buckets[idx]["trains"]), conflict_count=buckets[idx]["conflicts"], total_estimated_delay=0.0),
            )

    return [
        TimelineBucket(
            timestamp=now + timedelta(minutes=i * bucket_minutes),
            affected_trains=len(b["trains"]),
            conflicts=b["conflicts"],
            network_impact_score=b["score"],
        )
        for i, b in enumerate(buckets)
    ]
