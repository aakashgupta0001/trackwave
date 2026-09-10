"""Network Intelligence API (Phase 8).

Everything here is PREDICTED / ESTIMATED analytical output from RAILCAST's own
deterministic propagation model (see app/network/) — never a confirmed operational
fact, a signalling decision, or railway dispatching authority. `network_impact_score`
and `severity` are RAILCAST's own analytical scores, not an official risk classification.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.network import impact
from app.network.schemas import (
    AffectedTrain,
    ConflictType,
    ImpactSeverity,
    NetworkConflict,
    NetworkHotspot,
    NetworkOverviewResponse,
    TimelineBucket,
    TrainImpactResponse,
)
from app.schemas.common import Page, PaginationParams, build_page, get_pagination
from app.services.exceptions import NotFoundError

router = APIRouter(prefix="/network", tags=["network"])


@router.get(
    "/overview",
    response_model=NetworkOverviewResponse,
    summary="Network-wide predicted impact overview",
    description=(
        "Aggregates predicted network impact across every currently-delayed active train: "
        "how many trains/stations/sections are potentially affected, active predicted "
        "conflicts, hotspots, and an overall network impact score. All figures are RAILCAST "
        "analytical estimates, not confirmed operational information."
    ),
)
async def get_network_overview(
    journey_date: date | None = Query(default=None, description="Defaults to today"),
    session: AsyncSession = Depends(get_db),
) -> NetworkOverviewResponse:
    return await impact.analyze_network(session, journey_date)


@router.get(
    "/trains/{train_number}/impact",
    response_model=TrainImpactResponse,
    summary="Predicted network impact of one train's current delay",
    description=(
        "Given this train's current delay, estimates which other trains, stations, and "
        "sections may be affected via shared-section conflicts and delay propagation, "
        "plus an overall network impact score and severity. If the train has no currently "
        "known delay, returns a well-formed zero-impact result — not an error."
    ),
)
async def get_train_network_impact(
    train_number: str,
    journey_date: date | None = Query(default=None, description="Defaults to today"),
    session: AsyncSession = Depends(get_db),
) -> TrainImpactResponse:
    try:
        return await impact.analyze_train_impact(session, train_number, journey_date)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/affected-trains",
    response_model=Page[AffectedTrain],
    summary="Trains potentially affected by network delay propagation",
)
async def list_affected_trains(
    pagination: PaginationParams = Depends(get_pagination),
    severity: ImpactSeverity | None = Query(default=None),
    min_impact_score: int | None = Query(default=None, ge=0, le=100, description="Minimum estimated delay in minutes, used as a simple impact proxy per affected train"),
    journey_date: date | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> Page[AffectedTrain]:
    items = await impact.list_affected_trains(session, journey_date)
    if severity is not None:
        items = [a for a in items if a.impact_severity == severity]
    if min_impact_score is not None:
        items = [a for a in items if a.estimated_delay_minutes >= min_impact_score]
    total = len(items)
    page_items = items[pagination.offset : pagination.offset + pagination.page_size]
    return build_page(page_items, page=pagination.page, page_size=pagination.page_size, total=total)


@router.get(
    "/conflicts",
    response_model=Page[NetworkConflict],
    summary="Currently predicted shared-section conflicts",
)
async def list_network_conflicts(
    pagination: PaginationParams = Depends(get_pagination),
    severity: ImpactSeverity | None = Query(default=None),
    conflict_type: ConflictType | None = Query(default=None),
    section_code: str | None = Query(default=None),
    train_number: str | None = Query(default=None, description="Matches either side of the conflict"),
    journey_date: date | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> Page[NetworkConflict]:
    items = await impact.list_conflicts(session, journey_date)
    if severity is not None:
        items = [c for c in items if c.severity == severity]
    if conflict_type is not None:
        items = [c for c in items if c.conflict_type == conflict_type]
    if section_code is not None:
        items = [c for c in items if c.section_code == section_code.upper()]
    if train_number is not None:
        items = [c for c in items if train_number in (c.train_a, c.train_b)]
    total = len(items)
    page_items = items[pagination.offset : pagination.offset + pagination.page_size]
    return build_page(page_items, page=pagination.page, page_size=pagination.page_size, total=total)


@router.get(
    "/hotspots",
    response_model=list[NetworkHotspot],
    summary="Stations/sections where predicted impacts converge",
)
async def get_network_hotspots(
    journey_date: date | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> list[NetworkHotspot]:
    return await impact.list_hotspots(session, journey_date)


@router.get(
    "/timeline",
    response_model=list[TimelineBucket],
    summary="Time-bucketed predicted network impact across the analysis horizon",
    description=(
        "Forward-looking, not historical: buckets the analysis horizon by when each "
        "predicted conflict's overlap window is estimated to begin. RAILCAST does not "
        "store a time series of past network-impact scores."
    ),
)
async def get_network_timeline(
    journey_date: date | None = Query(default=None),
    bucket_minutes: int = Query(default=30, ge=5, le=180),
    session: AsyncSession = Depends(get_db),
) -> list[TimelineBucket]:
    return await impact.get_timeline(session, journey_date, bucket_minutes=bucket_minutes)
