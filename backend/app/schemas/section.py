from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RailwaySectionBase(BaseModel):
    section_code: str = Field(max_length=20)
    from_station_id: int
    to_station_id: int
    distance_km: float = Field(gt=0)
    scheduled_running_minutes: int = Field(gt=0)
    average_running_minutes: int = Field(gt=0)
    speed_limit_kmph: int = Field(gt=0)
    zone: str = Field(max_length=10)


class RailwaySectionCreate(RailwaySectionBase):
    pass


class RailwaySectionRead(RailwaySectionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
