"""Station-facing read-only APIs.

Note on `/stations/{station_code}/board`: it is explicitly NOT an ETA/prediction board.
`StationBoardItem.status` (ON_TIME/DELAYED/NO_RECENT_DATA) is derived purely from the
train's latest already-observed `TrainEvent.delay_minutes` — never a forecast. Predicted
arrival times belong to a later phase's ETA fusion engine.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.enums import StationType
from app.schemas.common import Page, PaginationParams, build_page, get_pagination
from app.schemas.station import StationBoardResponse, StationDetail, StationListItem, StationTrainItem
from app.services import station_service
from app.services.exceptions import NotFoundError

router = APIRouter(prefix="/stations", tags=["stations"])


@router.get("", response_model=Page[StationListItem], summary="List stations")
async def list_stations(
    pagination: PaginationParams = Depends(get_pagination),
    search: str | None = Query(default=None, description="Match against station code or name"),
    zone: str | None = Query(default=None),
    state: str | None = Query(default=None),
    station_type: StationType | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> Page[StationListItem]:
    stations, total = await station_service.list_stations_paginated(
        session,
        offset=pagination.offset,
        limit=pagination.page_size,
        search=search,
        zone=zone,
        state=state,
        station_type=station_type,
    )
    items = [StationListItem.model_validate(station) for station in stations]
    return build_page(items, page=pagination.page, page_size=pagination.page_size, total=total)


@router.get("/{station_code}", response_model=StationDetail, summary="Get station details")
async def get_station(station_code: str, session: AsyncSession = Depends(get_db)) -> StationDetail:
    try:
        station = await station_service.get_station(session, station_code)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return StationDetail.model_validate(station)


@router.get(
    "/{station_code}/board",
    response_model=StationBoardResponse,
    summary="Get the station's operational board (latest known info, not predicted ETAs)",
)
async def get_station_board(station_code: str, session: AsyncSession = Depends(get_db)) -> StationBoardResponse:
    try:
        return await station_service.get_station_board(session, station_code)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/{station_code}/trains",
    response_model=Page[StationTrainItem],
    summary="List trains scheduled to stop at this station",
)
async def get_station_trains(
    station_code: str,
    pagination: PaginationParams = Depends(get_pagination),
    search: str | None = Query(default=None, description="Match against train number or name"),
    session: AsyncSession = Depends(get_db),
) -> Page[StationTrainItem]:
    try:
        _station, items, total = await station_service.list_station_trains_paginated(
            session, station_code, offset=pagination.offset, limit=pagination.page_size, search=search
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return build_page(items, page=pagination.page, page_size=pagination.page_size, total=total)
