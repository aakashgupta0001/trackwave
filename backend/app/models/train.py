from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import TrainPriority, TrainType

if TYPE_CHECKING:
    from app.models.alert import Alert
    from app.models.prediction import Prediction
    from app.models.route import TrainRoute
    from app.models.station import Station
    from app.models.train_event import TrainEvent


class Train(Base):
    """A train service definition (its identity + timetable), not a specific day's run.

    Actual movement on a given day is represented by TrainEvent/Prediction rows, which
    carry real timestamps — see TrainRoute for why the schedule itself stays date-free.
    """

    __tablename__ = "trains"
    __table_args__ = (
        Index("ix_trains_active", "active"),
        # Backs the `zone` filter on GET /api/v1/trains (Phase 3).
        Index("ix_trains_zone", "zone"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    train_number: Mapped[str] = mapped_column(String(10), unique=True, index=True, nullable=False)
    train_name: Mapped[str] = mapped_column(String(100), nullable=False)
    train_type: Mapped[TrainType] = mapped_column(
        SAEnum(TrainType, name="train_type_enum", native_enum=False, validate_strings=True, length=20),
        nullable=False,
    )
    source_station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), nullable=False, index=True)
    destination_station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), nullable=False, index=True)
    zone: Mapped[str] = mapped_column(String(10), nullable=False)
    priority: Mapped[TrainPriority] = mapped_column(
        SAEnum(TrainPriority, name="train_priority_enum", native_enum=False, validate_strings=True, length=10),
        nullable=False,
        default=TrainPriority.NORMAL,
        server_default=TrainPriority.NORMAL.value,
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    source_station: Mapped["Station"] = relationship(
        foreign_keys=[source_station_id], back_populates="trains_originating"
    )
    destination_station: Mapped["Station"] = relationship(
        foreign_keys=[destination_station_id], back_populates="trains_terminating"
    )
    routes: Mapped[list["TrainRoute"]] = relationship(
        back_populates="train", cascade="all, delete-orphan", order_by="TrainRoute.sequence_number"
    )
    events: Mapped[list["TrainEvent"]] = relationship(back_populates="train", cascade="all, delete-orphan")
    predictions: Mapped[list["Prediction"]] = relationship(back_populates="train", cascade="all, delete-orphan")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="train", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Train {self.train_number}>"
