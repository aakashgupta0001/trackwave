"""Network intelligence (Phase 8) data shapes — both the internal domain objects the
graph/propagation/conflict modules pass around, and the public API response schemas.

TERMINOLOGY (module 46 of the spec): every number here is a RAILCAST analytical
estimate, not a confirmed operational fact. Fields are named `estimated_*`/`predicted_*`
throughout, `impact_score`/`severity` are explicitly RAILCAST's own scoring, and nothing
in this module represents signalling, interlocking, or dispatching authority.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ImpactSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ConflictType(str, Enum):
    SHARED_SECTION_OVERLAP = "SHARED_SECTION_OVERLAP"
    INSUFFICIENT_SEPARATION = "INSUFFICIENT_SEPARATION"
    DOWNSTREAM_DELAY_EXPOSURE = "DOWNSTREAM_DELAY_EXPOSURE"


class NetworkAnalysisStatus(str, Enum):
    OK = "OK"
    # Route/section data was incomplete for (part of) the analysis — module 37.
    LIMITED = "LIMITED"


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# --- internal domain objects (graph.py / resolver.py / conflict.py / propagation.py) ---


class StopWindow(BaseModel):
    """One train's estimated occupation of one section, derived from its route plus
    whatever delay is currently known for it. Not persisted — recomputed per analysis.
    """

    section_id: int
    section_code: str
    from_station_code: str
    to_station_code: str
    sequence_number: int  # sequence number of the route entry arriving via this section
    entry_time: datetime
    exit_time: datetime
    delay_minutes: float
    is_estimated: bool = Field(description="False only for the untouched static schedule (zero known delay)")


class PropagationResult(BaseModel):
    estimated_delay_minutes: float
    propagation_factor: float = Field(description="source_delay multiplier actually applied, post-decay")
    confidence: ConfidenceLevel
    depth: int


# --- reasons / explanations (module 14, 28 — deterministic templates, no LLM) ----------


class ImpactReason(BaseModel):
    type: str
    description: str
    confidence: ConfidenceLevel


# --- API-facing response models ---------------------------------------------------------


class SectionRef(BaseModel):
    section_code: str
    from_station_code: str
    to_station_code: str


class NetworkConflict(BaseModel):
    conflict_type: ConflictType
    severity: ImpactSeverity
    train_a: str
    train_b: str
    section_code: str | None = None
    station_code: str | None = None
    estimated_overlap_minutes: float | None = None
    separation_minutes: float | None = None
    directional_confidence: ConfidenceLevel = Field(
        description="HIGH when both trains' direction on the shared section is known and identical"
    )
    reason: ImpactReason
    predicted_at: datetime | None = Field(
        default=None, description="Estimated start of the overlap/exposure window — powers the timeline API"
    )


class AffectedTrain(BaseModel):
    source_train_number: str
    train_number: str
    train_name: str
    section_code: str | None = None
    station_code: str | None = None
    estimated_delay_minutes: float
    lower_delay_minutes: float | None = None
    upper_delay_minutes: float | None = None
    propagation_depth: int
    impact_severity: ImpactSeverity
    impact_confidence: ConfidenceLevel
    reason: ImpactReason


class StationImpact(BaseModel):
    station_code: str
    station_name: str
    affected_train_count: int
    estimated_delay_minutes: float
    severity: ImpactSeverity
    latitude: float | None = None
    longitude: float | None = None


class SectionImpact(BaseModel):
    section_code: str
    from_station_code: str
    to_station_code: str
    affected_trains: int
    estimated_delay_minutes: float
    conflict_count: int
    severity: ImpactSeverity


class NetworkHotspot(BaseModel):
    entity_type: str = Field(description="STATION | SECTION")
    entity_code: str
    entity_name: str
    affected_trains: int
    conflict_count: int
    impact_score: int = Field(ge=0, le=100)
    severity: ImpactSeverity


class TrainImpactResponse(BaseModel):
    train_number: str
    train_name: str
    analysis_status: NetworkAnalysisStatus
    source_delay_minutes: float
    network_impact_score: int = Field(ge=0, le=100)
    severity: ImpactSeverity
    affected_trains: list[AffectedTrain]
    affected_stations: list[StationImpact]
    affected_sections: list[SectionImpact]
    conflicts: list[NetworkConflict]
    generated_at: datetime
    horizon_minutes: int
    notes: list[str] = Field(default_factory=list)


class NetworkOverviewResponse(BaseModel):
    generated_at: datetime
    analysis_status: NetworkAnalysisStatus
    total_trains_monitored: int
    delayed_trains: int
    affected_trains: int
    affected_stations: int
    affected_sections: int
    active_conflicts: int
    hotspots: list[NetworkHotspot]
    network_impact_score: int = Field(ge=0, le=100)
    severity: ImpactSeverity
    horizon_minutes: int
    notes: list[str] = Field(default_factory=list)


class TimelineBucket(BaseModel):
    timestamp: datetime
    affected_trains: int
    conflicts: int
    network_impact_score: int = Field(ge=0, le=100)
