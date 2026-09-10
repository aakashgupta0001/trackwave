from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Integer, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import EventSource, EventType

if TYPE_CHECKING:
    from app.models.section import RailwaySection
    from app.models.station import Station
    from app.models.train import Train


class TrainEvent(Base):
    """An observed/simulated train movement or operational event.

    Note: the Python attribute is `event_metadata` (not `metadata`) because SQLAlchemy's
    DeclarativeBase reserves `metadata` for the ORM's own table registry; the underlying
    DB column is still named `metadata`, matching the API/spec naming.
    """

    __tablename__ = "train_events"
    __table_args__ = (
        CheckConstraint(
            "latitude IS NULL OR (latitude >= -90 AND latitude <= 90)", name="ck_train_event_latitude_range"
        ),
        CheckConstraint(
            "longitude IS NULL OR (longitude >= -180 AND longitude <= 180)", name="ck_train_event_longitude_range"
        ),
        CheckConstraint("speed_kmph IS NULL OR speed_kmph >= 0", name="ck_train_event_speed_non_negative"),
        Index("ix_train_events_train_id_timestamp", "train_id", "timestamp"),
        Index("ix_train_events_section_id_timestamp", "section_id", "timestamp"),
        Index("ix_train_events_station_id", "station_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    train_id: Mapped[int] = mapped_column(ForeignKey("trains.id", ondelete="CASCADE"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    speed_kmph: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    station_id: Mapped[int | None] = mapped_column(ForeignKey("stations.id"), nullable=True)
    section_id: Mapped[int | None] = mapped_column(ForeignKey("railway_sections.id"), nullable=True)
    delay_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    event_type: Mapped[EventType] = mapped_column(
        SAEnum(EventType, name="event_type_enum", native_enum=False, validate_strings=True, length=30),
        nullable=False,
    )
    event_source: Mapped[EventSource] = mapped_column(
        SAEnum(EventSource, name="event_source_enum", native_enum=False, validate_strings=True, length=20),
        nullable=False,
    )
    event_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    train: Mapped["Train"] = relationship(back_populates="events")
    station: Mapped["Station | None"] = relationship(back_populates="events")
    section: Mapped["RailwaySection | None"] = relationship(back_populates="events")

    def __repr__(self) -> str:
        return f"<TrainEvent train_id={self.train_id} type={self.event_type}>"
