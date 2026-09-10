from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import PredictionMode

if TYPE_CHECKING:
    from app.models.station import Station
    from app.models.train import Train


class Prediction(Base):
    """A stored ETA prediction. Populated by the ETA fusion engine starting Phase 8+.

    All prediction-specific fields are nullable — Phase 2 only defines the storage
    shape, it does not compute ETAs.
    """

    __tablename__ = "predictions"
    __table_args__ = (
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_prediction_confidence_range"),
        Index("ix_predictions_train_id_timestamp", "train_id", "prediction_timestamp"),
        Index("ix_predictions_station_id_timestamp", "station_id", "prediction_timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    train_id: Mapped[int] = mapped_column(ForeignKey("trains.id", ondelete="CASCADE"), nullable=False)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), nullable=False)
    prediction_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    baseline_eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ml_correction_minutes: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    final_eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lower_bound: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    upper_bound: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    prediction_mode: Mapped[PredictionMode | None] = mapped_column(
        SAEnum(PredictionMode, name="prediction_mode_enum", native_enum=False, validate_strings=True, length=20),
        nullable=True,
    )
    actual_arrival: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_minutes: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)

    # --- Phase 7: uncertainty & confidence --------------------------------------------
    # Structured, queryable fields for the interval and confidence summary. Explanations
    # are deliberately NOT stored here (avoid huge SHAP payloads; they are served
    # on demand and cached in Redis keyed by state + model version).
    lower_eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    upper_eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    interval_level: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    confidence_score: Mapped[int | None] = mapped_column(nullable=True)
    confidence_level: Mapped[str | None] = mapped_column(String(10), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    train: Mapped["Train"] = relationship(back_populates="predictions")
    station: Mapped["Station"] = relationship(back_populates="predictions")

    def __repr__(self) -> str:
        return f"<Prediction train_id={self.train_id} station_id={self.station_id}>"
