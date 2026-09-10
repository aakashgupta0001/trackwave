from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.alert import Alert
    from app.models.route import TrainRoute
    from app.models.station import Station
    from app.models.train_event import TrainEvent


class RailwaySection(Base):
    """A track section between two adjacent stations.

    Distances and running times here are prototype/sample values for demonstration
    purposes — not official Indian Railways operational data.
    """

    __tablename__ = "railway_sections"
    __table_args__ = (
        CheckConstraint("from_station_id != to_station_id", name="ck_section_distinct_stations"),
        CheckConstraint("distance_km > 0", name="ck_section_distance_positive"),
        CheckConstraint("scheduled_running_minutes > 0", name="ck_section_scheduled_running_positive"),
        CheckConstraint("average_running_minutes > 0", name="ck_section_average_running_positive"),
        CheckConstraint("speed_limit_kmph > 0", name="ck_section_speed_limit_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    section_code: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    from_station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), nullable=False, index=True)
    to_station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), nullable=False, index=True)
    distance_km: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    scheduled_running_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    average_running_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    speed_limit_kmph: Mapped[int] = mapped_column(Integer, nullable=False)
    zone: Mapped[str] = mapped_column(String(10), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    from_station: Mapped["Station"] = relationship(foreign_keys=[from_station_id], back_populates="sections_from")
    to_station: Mapped["Station"] = relationship(foreign_keys=[to_station_id], back_populates="sections_to")
    routes: Mapped[list["TrainRoute"]] = relationship(back_populates="section")
    events: Mapped[list["TrainEvent"]] = relationship(back_populates="section")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="section")

    def __repr__(self) -> str:
        return f"<RailwaySection {self.section_code}>"
