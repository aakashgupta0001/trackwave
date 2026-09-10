from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.enums import EventType, TrainType
from app.schemas.common import Page, PaginationParams, build_page, get_pagination
from app.schemas.route import TrainRouteItem, TrainRouteResponse, TrainUpcomingResponse
from app.schemas.train import TrainDetail, TrainListItem
from app.schemas.train_event import TrainEventResponse, TrainStateResponse
from app.services import train_service
from app.services.exceptions import NotFoundError

router = APIRouter(prefix="/trains", tags=["trains"])


@router.get("", response_model=Page[TrainListItem], summary="List trains")
async def list_trains(
    pagination: PaginationParams = Depends(get_pagination),
    search: str | None = Query(default=None, description="Match against train number or name"),
    train_type: TrainType | None = Query(default=None),
    zone: str | None = Query(default=None),
    active: bool | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> Page[TrainListItem]:
    trains, total = await train_service.list_trains_paginated(
        session,
        offset=pagination.offset,
        limit=pagination.page_size,
        search=search,
        train_type=train_type,
        zone=zone,
        active=active,
    )
    items = [TrainListItem.from_train(train) for train in trains]
    return build_page(items, page=pagination.page, page_size=pagination.page_size, total=total)


@router.get("/{train_number}", response_model=TrainDetail, summary="Get train details")
async def get_train(train_number: str, session: AsyncSession = Depends(get_db)) -> TrainDetail:
    try:
        train = await train_service.get_train_with_route(session, train_number)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return TrainDetail.from_train(train)


@router.get("/{train_number}/route", response_model=TrainRouteResponse, summary="Get a train's full scheduled route")
async def get_train_route(train_number: str, session: AsyncSession = Depends(get_db)) -> TrainRouteResponse:
    try:
        train, route = await train_service.get_train_route(session, train_number)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return TrainRouteResponse(
        train_number=train.train_number,
        train_name=train.train_name,
        source=train.source_station.station_code,
        destination=train.destination_station.station_code,
        route=[TrainRouteItem.from_route(entry) for entry in route],
    )


@router.get(
    "/{train_number}/upcoming",
    response_model=TrainUpcomingResponse,
    summary="Get a train's remaining scheduled stops based on its latest known position",
)
async def get_train_upcoming(train_number: str, session: AsyncSession = Depends(get_db)) -> TrainUpcomingResponse:
    try:
        train, latest_event, upcoming = await train_service.get_upcoming_route(session, train_number)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return TrainUpcomingResponse(
        train_number=train.train_number,
        train_name=train.train_name,
        has_known_state=latest_event is not None,
        as_of=latest_event.timestamp if latest_event is not None else None,
        current_station_code=(
            latest_event.station.station_code if latest_event is not None and latest_event.station is not None else None
        ),
        current_section_code=(
            latest_event.section.section_code if latest_event is not None and latest_event.section is not None else None
        ),
        current_delay_minutes=latest_event.delay_minutes if latest_event is not None else None,
        upcoming=[TrainRouteItem.from_route(entry) for entry in upcoming],
    )


@router.get(
    "/{train_number}/state",
    response_model=TrainStateResponse,
    summary="Get a train's latest known operational state",
)
async def get_train_state(train_number: str, session: AsyncSession = Depends(get_db)) -> TrainStateResponse:
    try:
        _train, latest_event = await train_service.get_train_state(session, train_number)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if latest_event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"No known state for train {train_number}"
        )

    return TrainStateResponse.from_event(train_number, latest_event, now=datetime.now(timezone.utc))


@router.get("/{train_number}/events", response_model=Page[TrainEventResponse], summary="List a train's movement events")
async def list_train_events(
    train_number: str,
    pagination: PaginationParams = Depends(get_pagination),
    event_type: EventType | None = Query(default=None),
    from_timestamp: datetime | None = Query(default=None),
    to_timestamp: datetime | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> Page[TrainEventResponse]:
    try:
        _train, events, total = await train_service.list_train_events_paginated(
            session,
            train_number,
            offset=pagination.offset,
            limit=pagination.page_size,
            event_type=event_type,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    items = [TrainEventResponse.from_event(event) for event in events]
    return build_page(items, page=pagination.page, page_size=pagination.page_size, total=total)
