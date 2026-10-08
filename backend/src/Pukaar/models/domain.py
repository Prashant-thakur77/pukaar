from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Site(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    region: str
    lat: float
    lng: float
    description: Optional[str] = None
    is_active: bool = True


class SiteExperimentalSettings(SQLModel, table=True):
    site_id: str = Field(primary_key=True)
    historical_context_enabled: bool = False
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class VolunteerReport(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    reporter_name: str
    reporter_role: str
    photo_path: Optional[str] = None
    audio_path: Optional[str] = None
    transcript_text: str
    offline_created: bool = False


class ParsedObservation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    volunteer_report_id: int = Field(index=True)
    water_level_category: str
    trend: str
    road_status: str
    bridge_status: str
    homes_affected: bool
    urgency: str
    confidence: float
    structured_json: str
    decision_trace: str
    parser_source: str = "rules"
    severity_score: float = 0.0
    summary: str = ""


class HydrometSnapshot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    provider: str = "open-meteo"
    weather_code: Optional[int] = None
    precipitation_mm: float = 0.0
    rain_mm: float = 0.0
    precipitation_probability: float = 0.0
    river_discharge: Optional[float] = None
    river_discharge_max: Optional[float] = None
    river_discharge_trend: Optional[float] = None
    signal_score: float = 0.0
    summary: str = ""
    raw_payload: str = "{}"


class FusedAlert(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: str = Field(index=True)
    incident_id: Optional[int] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    level: str
    score: float
    trigger_source: str
    summary: str
    decision_trace: str
    local_alarm_triggered: bool = False
    reasoning_summary: Optional[str] = None
    reasoning_chain: Optional[str] = None
    reasoning_model: Optional[str] = None


class Incident(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: str = Field(index=True)
    current_level: str = "green"
    lifecycle_state: str = "monitoring"
    opened_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    closed_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
    close_reason: Optional[str] = None
    evidence_window_minutes: int = 45
    summary: str = ""


class ActuationRecord(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    alert_id: Optional[int] = Field(default=None, index=True)
    incident_id: Optional[int] = Field(default=None, index=True)
    site_id: str = Field(index=True)
    actuator_type: str = Field(index=True)
    payload: str = "{}"
    status: str = "pending"
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
