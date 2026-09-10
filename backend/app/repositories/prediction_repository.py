from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PredictionMode
from app.models.prediction import Prediction
from app.models.station import Station
from app.schemas.prediction import PredictionCreate


async def get_by_id(session: AsyncSession, prediction_id: int) -> Prediction | None:
    return await session.get(Prediction, prediction_id)


async def list_for_train(session: AsyncSession, train_id: int, *, limit: int = 200) -> list[Prediction]:
    result = await session.execute(
        select(Prediction)
        .where(Prediction.train_id == train_id)
        .order_by(Prediction.prediction_timestamp.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def create(session: AsyncSession, data: PredictionCreate) -> Prediction:
    prediction = Prediction(**data.model_dump())
    session.add(prediction)
    await session.flush()
    return prediction


async def upsert_baseline(
    session: AsyncSession,
    *,
    train_id: int,
    station_code: str,
    prediction_timestamp: datetime,
    scheduled_eta: datetime | None,
    baseline_eta: datetime | None,
    prediction_mode: PredictionMode,
    model_version: str | None,
    ml_correction_minutes: float | None = None,
    final_eta: datetime | None = None,
    lower_eta: datetime | None = None,
    upper_eta: datetime | None = None,
    interval_level: float | None = None,
    confidence_score: int | None = None,
    confidence_level: str | None = None,
) -> Prediction | None:
    """Idempotent write of one baseline/fused prediction: RAILCAST keeps ONE current row
    per (train, station, mode) and refreshes it in place instead of accumulating a row
    per computation. ml_correction_minutes is null unless the Phase 6 residual model
    actually produced a value."""
    result = await session.execute(
        select(Prediction)
        .join(Station, Station.id == Prediction.station_id)
        .where(
            Prediction.train_id == train_id,
            Station.station_code == station_code,
            Prediction.prediction_mode == prediction_mode,
        )
        .order_by(Prediction.prediction_timestamp.desc())
        .limit(1)
    )
    prediction = result.scalar_one_or_none()
    if prediction is not None:
        prediction.prediction_timestamp = prediction_timestamp
        prediction.scheduled_eta = scheduled_eta
        prediction.baseline_eta = baseline_eta
        prediction.ml_correction_minutes = ml_correction_minutes
        prediction.final_eta = final_eta
        prediction.model_version = model_version
        prediction.lower_eta = lower_eta
        prediction.upper_eta = upper_eta
        prediction.interval_level = interval_level
        prediction.confidence_score = confidence_score
        prediction.confidence_level = confidence_level
        await session.flush()
        return prediction

    station = (await session.execute(select(Station).where(Station.station_code == station_code).limit(1))).scalar_one_or_none()
    if station is None:
        return None
    prediction = Prediction(
        train_id=train_id,
        station_id=station.id,
        prediction_timestamp=prediction_timestamp,
        scheduled_eta=scheduled_eta,
        baseline_eta=baseline_eta,
        ml_correction_minutes=ml_correction_minutes,
        final_eta=final_eta,
        prediction_mode=prediction_mode,
        model_version=model_version,
        lower_eta=lower_eta,
        upper_eta=upper_eta,
        interval_level=interval_level,
        confidence_score=confidence_score,
        confidence_level=confidence_level,
    )
    session.add(prediction)
    await session.flush()
    return prediction


async def backfill_actual_arrivals(session: AsyncSession, train_id: int, station_id: int, actual_arrival: datetime) -> int:
    """Outcome backfill (Phase 6, module 29): once an arrival is actually observed,
    update the stored predictions for that train/station whose ETA horizon has passed —
    never during real-time inference, only with the now-known outcome. Returns the
    number of predictions updated."""
    from app.models.prediction import Prediction

    result = await session.execute(
        select(Prediction).where(
            Prediction.train_id == train_id,
            Prediction.station_id == station_id,
            Prediction.actual_arrival.is_(None),
            Prediction.prediction_timestamp < actual_arrival,
        )
    )
    predictions = result.scalars().all()
    updated = 0
    for prediction in predictions:
        prediction.actual_arrival = actual_arrival
        if prediction.final_eta is not None:
            prediction.error_minutes = (actual_arrival - prediction.final_eta).total_seconds() / 60.0
        updated += 1
    if updated:
        await session.flush()
    return updated
