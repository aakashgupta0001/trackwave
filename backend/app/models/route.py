from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, Time, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.section import RailwaySection
    from app.models.station import Station
    from app.models.train import Train


class TrainRoute(Base):
    """One station stop in a train's static timetable.

    Design decision — `scheduled_arrival`/`scheduled_departure` are stored as clock
    `Time` values plus a `day_offset` (days elapsed since the train's origin departure),
    not as absolute datetimes. A TrainRoute row is a *template* describing the train's
    recurring schedule, not a specific day's journey — baking a calendar date into it
    would conflate "when this train stops here on any given run" with "when it stopped
    here on one particular day." Actual dated events belong to TrainEvent/Prediction,
    which already carry real timestamps. `day_offset` exists because journeys spanning
    multiple nights (e.g. Nagpur/Mumbai legs) need to distinguish 08:10 on day 0 from
    08:10 on day 1.
    """

    __tablename__ = "train_routes"
    __table_args__ = (
        UniqueConstraint("train_id", "sequence_number", name="uq_train_route_sequence"),
        CheckConstraint("halt_minutes >= 0", name="ck_train_route_halt_non_negative"),
        CheckConstraint("distance_from_origin_km >= 0", name="ck_train_route_distance_non_negative"),
        CheckConstraint("day_offset >= 0", name="ck_train_route_day_offset_non_negative"),
        Index("ix_train_routes_train_id", "train_id"),
        Index("ix_train_routes_station_id", "station_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    train_id: Mapped[int] = mapped_column(ForeignKey("trains.id", ondelete="CASCADE"), nullable=False)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), nullable=False)
    section_id: Mapped[int | None] = mapped_column(ForeignKey("railway_sections.id"), nullable=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_arrival: Mapped[time | None] = mapped_column(Time, nullable=True)
    scheduled_departure: Mapped[time | None] = mapped_column(Time, nullable=True)
    day_offset: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    halt_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    distance_from_origin_km: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    train: Mapped["Train"] = relationship(back_populates="routes")
    station: Mapped["Station"] = relationship(back_populates="route_entries")
    section: Mapped["RailwaySection | None"] = relationship(back_populates="routes")

    def __repr__(self) -> str:
        return f"<TrainRoute train_id={self.train_id} seq={self.sequence_number}>"
