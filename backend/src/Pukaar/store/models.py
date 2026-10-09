"""Domain records. Plain Pydantic models; the repo maps them to DynamoDB items."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Level = Literal["normal", "watch", "warning", "critical"]
LEVELS: tuple[str, ...] = ("normal", "watch", "warning", "critical")

AlertStatus = Literal[
    "drafting",
    "pending",
    "approved",
    "declined",
    "expired",
    "delivering",
    "delivered",
    "auto_sent_unapproved",
    "failsafe",
    "closed",
]
OPEN_ALERT_STATUSES = {"drafting", "pending", "approved", "delivering"}

ReportState = Literal[
    "received",
    "transcribing",
    "unverified",
    "verified_auto",
    "verified",
    "reviewed",
    "actioned",
    "resolved",
    "duplicate",
    "false",
]
VERIFIED_STATES = {"verified_auto", "verified", "reviewed", "actioned", "resolved"}
ReportType = Literal[
    "water_rising", "road_cut", "bridge_unsafe", "landslide", "homes_affected", "people_trapped", "other"
]
Severity = Literal["low", "medium", "high", "critical"]
DirectiveType = Literal["evacuate", "shelter_in_place", "advisory", "all_clear"]


def level_rank(level: str) -> int:
    return LEVELS.index(level) if level in LEVELS else 0


class Thresholds(BaseModel):
    watch: float
    warning: float
    critical: float
    source: str = "open-meteo flood API daily history 1984-2024"


class Village(BaseModel):
    id: str
    name: str
    name_hi: str
    district: str
    lat: float
    lon: float
    coords_verified: bool = False
    coords_source: str | None = None
    population: int | None = None
    officers: list[str] = Field(default_factory=list)  # officer usernames, in call order
    level: Level = "normal"
    level_since: str | None = None
    calm_sweeps: int = 0
    thresholds: Thresholds | None = None
    open_alert_id: str | None = None
    replay: bool = False


class Reading(BaseModel):
    village_id: str
    at: str
    rain_24h_mm: float | None = None
    rain_hourly: list[dict[str, Any]] = Field(default_factory=list)
    discharge: float | None = None
    discharge_forecast: list[dict[str, Any]] = Field(default_factory=list)
    discharge_peak: float | None = None
    rain_level: Level = "normal"
    river_level: Level = "normal"
    source: str = "open-meteo"
    replay: bool = False


class Report(BaseModel):
    id: str
    village_id: str
    created_at: str
    text: str = ""
    transcript: str = ""
    report_type: ReportType = "other"
    severity: Severity = "low"
    summary_en: str = ""
    reply_hi: str = ""
    lat: float | None = None
    lon: float | None = None
    photo_key: str | None = None
    audio_key: str | None = None
    photo_description: str | None = None
    state: ReportState = "received"
    previous_state: ReportState | None = None
    parser_source: str = "rules"
    flags: list[str] = Field(default_factory=list)
    track_code: str = ""
    reporter_name: str | None = None
    offline_created: bool = False
    verified_by: str | None = None
    acted_at: str | None = None
    replay: bool = False


class DraftCheck(BaseModel):
    passed: bool
    reason: str


class Alert(BaseModel):
    id: str
    village_id: str
    village_name: str
    village_name_hi: str
    level: Level
    previous_level: Level = "normal"
    status: AlertStatus = "drafting"
    created_at: str
    updated_at: str
    text_hi: str = ""
    text_en: str = ""
    reason_en: str = ""
    reasoning_model: str = "rule-fallback"
    draft_check: DraftCheck | None = None
    decision_trace: dict[str, Any] = Field(default_factory=dict)
    recipients_count: int = 0
    officer_index: int = 0
    decided_by: str | None = None
    decided_at: str | None = None
    approved: bool = False
    delivered_count: int = 0
    acknowledged_count: int = 0
    audio_key: str | None = None
    task_token: str | None = None
    token_version: int = 0
    execution_arn: str | None = None
    replay: bool = False


class Recipient(BaseModel):
    id: str  # telegram chat id or "stub-..." for demo recipients
    village_id: str
    name: str
    role: Literal["villager", "pradhan", "officer"] = "villager"
    channel: Literal["telegram", "stub"] = "telegram"
    language: str = "hi"


class Delivery(BaseModel):
    alert_id: str
    recipient_id: str
    name: str
    channel: str
    status: Literal["pending", "sent", "failed", "acknowledged"] = "pending"
    sent_at: str | None = None
    attempts: int = 0
    acknowledged_at: str | None = None
    error: str | None = None


class Directive(BaseModel):
    id: str
    village_id: str
    type: DirectiveType
    text_hi: str
    text_en: str
    issued_by: str
    issued_at: str
    active: bool = True


class AuditRow(BaseModel):
    at: str
    id: str
    actor: str
    role: str
    action: str
    resource: str
    decision: Literal["allow", "deny"]
    reason: str


class TimelineEvent(BaseModel):
    at: str
    step: str
    detail: str = ""


class PastEvent(BaseModel):
    village_id: str
    date: str
    level: Level
    note_en: str
    note_hi: str = ""
    source: str


class ReplayState(BaseModel):
    active: bool = False
    scenario: str | None = None
    clock: str | None = None
    hours_total: int = 0
    hours_done: int = 0
    started_at: str | None = None
    updated_at: str | None = None
    source: str | None = None
