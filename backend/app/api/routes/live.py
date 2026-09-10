"""Live train/station data — sourced from whichever provider is configured (see
app/providers/), never computed or predicted here. These endpoints never calculate ETA;
that's a later phase's job.

A 404 here means the train/station doesn't exist in RAILCAST's own digital twin (Phase 2).
It's different from `data_status: UNAVAILABLE`, which means the resource is real but no
configured provider currently has data for it — that's a normal 200 response, not an error.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.providers.manager import provider_manager
from app.schemas.live import LiveStationBoardResponse, LiveTrainRouteResponse, LiveTrainStateResponse
from app.services import station_service, train_service
from app.services.exceptions import NotFoundError

router = APIRouter(tags=["live"])


@router.get(
    "/live/trains/{train_number}",
    response_model=LiveTrainStateResponse,
    summary="Get a train's live/simulated position and delay, from the configured provider",
)
async def get_live_train_state(
    train_number: str,
    journey_date: date | None = Query(default=None, description="Defaults to today"),
    session: AsyncSession = Depends(get_db),
) -> LiveTrainStateResponse:
    try:
        await train_service.get_train_with_route(session, train_number)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    result = await provider_manager.get_train_status(session, train_number, journey_date or date.today())
    return LiveTrainStateResponse.from_result(train_number, result)


@router.get(
    "/live/trains/{train_number}/route",
    response_model=LiveTrainRouteResponse,
    summary="Get a train's route as reported by the configured provider (not RAILCAST's own schedule)",
)
async def get_live_train_route(train_number: str, session: AsyncSession = Depends(get_db)) -> LiveTrainRouteResponse:
    try:
        await train_service.get_train_with_route(session, train_number)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    result = await provider_manager.get_train_route(session, train_number)
    return LiveTrainRouteResponse.from_result(train_number, result)


@router.get(
    "/live/stations/{station_code}",
    response_model=LiveStationBoardResponse,
    summary="Get a station's live operational board from the configured provider",
)
async def get_live_station_board(station_code: str, session: AsyncSession = Depends(get_db)) -> LiveStationBoardResponse:
    try:
        await station_service.get_station(session, station_code)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    result = await provider_manager.get_station_status(session, station_code)
    return LiveStationBoardResponse.from_result(station_code, result)
