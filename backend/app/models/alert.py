from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import AlertSeverity, AlertType

if TYPE_CHECKING:
    from app.models.section import RailwaySection
    from app.models.station import Station
    from app.models.train import Train


class Alert(Base):
    """An operational alert. `train_id`/`section_id`/`station_id` are all nullable —
    an alert may apply to any subset of those (e.g. a congestion alert on a section
    with no specific train involved).

    As with TrainEvent, the Python attribute is `alert_metadata` (DB column: `metadata`)
    to avoid colliding with SQLAlchemy's reserved `Base.metadata`.
    """

    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_severity", "severity"),
        Index("ix_alerts_resolved_at", "resolved_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_type: Mapped[AlertType] = mapped_column(
        SAEnum(AlertType, name="alert_type_enum", native_enum=False, validate_strings=True, length=30),
        nullable=False,
    )
    severity: Mapped[AlertSeverity] = mapped_column(
        SAEnum(AlertSeverity, name="alert_severity_enum", native_enum=False, validate_strings=True, length=10),
        nullable=False,
    )
    train_id: Mapped[int | None] = mapped_column(ForeignKey("trains.id", ondelete="CASCADE"), nullable=True)
    section_id: Mapped[int | None] = mapped_column(ForeignKey("railway_sections.id"), nullable=True)
    station_id: Mapped[int | None] = mapped_column(ForeignKey("stations.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    alert_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    train: Mapped["Train | None"] = relationship(back_populates="alerts")
    section: Mapped["RailwaySection | None"] = relationship(back_populates="alerts")
    station: Mapped["Station | None"] = relationship(back_populates="alerts")

    def __repr__(self) -> str:
        return f"<Alert {self.alert_type} severity={self.severity}>"
