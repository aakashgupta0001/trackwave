from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import StationType

if TYPE_CHECKING:
    from app.models.alert import Alert
    from app.models.prediction import Prediction
    from app.models.route import TrainRoute
    from app.models.section import RailwaySection
    from app.models.train import Train
    from app.models.train_event import TrainEvent


class Station(Base):
    """A railway station. Reference data — created via seed, rarely deleted."""

    __tablename__ = "stations"
    __table_args__ = (
        CheckConstraint("latitude >= -90 AND latitude <= 90", name="ck_station_latitude_range"),
        CheckConstraint("longitude >= -180 AND longitude <= 180", name="ck_station_longitude_range"),
        Index("ix_stations_zone", "zone"),
        # Backs the `state` filter on GET /api/v1/stations (Phase 3).
        Index("ix_stations_state", "state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    station_code: Mapped[str] = mapped_column(String(10), unique=True, index=True, nullable=False)
    station_name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    zone: Mapped[str] = mapped_column(String(10), nullable=False)
    division: Mapped[str | None] = mapped_column(String(50), nullable=True)
    state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    station_type: Mapped[StationType] = mapped_column(
        SAEnum(StationType, name="station_type_enum", native_enum=False, validate_strings=True, length=20),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    sections_from: Mapped[list["RailwaySection"]] = relationship(
        foreign_keys="RailwaySection.from_station_id", back_populates="from_station"
    )
    sections_to: Mapped[list["RailwaySection"]] = relationship(
        foreign_keys="RailwaySection.to_station_id", back_populates="to_station"
    )
    trains_originating: Mapped[list["Train"]] = relationship(
        foreign_keys="Train.source_station_id", back_populates="source_station"
    )
    trains_terminating: Mapped[list["Train"]] = relationship(
        foreign_keys="Train.destination_station_id", back_populates="destination_station"
    )
    route_entries: Mapped[list["TrainRoute"]] = relationship(back_populates="station")
    events: Mapped[list["TrainEvent"]] = relationship(back_populates="station")
    predictions: Mapped[list["Prediction"]] = relationship(back_populates="station")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="station")

    def __repr__(self) -> str:
        return f"<Station {self.station_code}>"
