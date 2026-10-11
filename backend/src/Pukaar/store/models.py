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
ShelterState = Literal["OPEN", "STANDBY", "FULL", "CLOSED"]
SHELTER_STATES: tuple[str, ...] = ("OPEN", "STANDBY", "FULL", "CLOSED")


def level_rank(level: str) -> int:
    return LEVELS.index(level) if level in LEVELS else 0


class Thresholds(BaseModel):
    watch: float
    warning: float
    critical: float
    source: str = "open-meteo flood API daily history 1984-2024"


class SoilRange(BaseModel):
    """The village's own root-zone soil moisture range (m³/m³): dry = 5th, wet = 95th percentile.

    Saturation S = (sm - dry) / (wet - dry), clipped to 0..1 (services/soil.py).
    """

    dry: float
    wet: float
    source: str = "default"


class GaugeConfig(BaseModel):
    """A river-stage gauge at the village (e.g. ESP32 + JSN-SR04T under a bridge deck).

    Stage is in cm above the gauge's own zero. Seeded values are illustrative
    until the gauge's own record exists (docs/hardware/README.md).
    """

    device_id: str
    watch_cm: float
    warning_cm: float
    critical_cm: float
    installed: bool = False
    note: str = ""


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
    gauge: GaugeConfig | None = None
    soil: SoilRange | None = None
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
    # Daily river discharge from today up to 7 days ahead: the "get ready" outlook (readiness.py).
    discharge_outlook: list[dict[str, Any]] = Field(default_factory=list)
    # Root-zone soil moisture now (m³/m³): mean of the 9-27 cm and 27-81 cm layers (soil.py).
    soil_moisture_root: float | None = None
    rain_level: Level = "normal"
    river_level: Level = "normal"
    source: str = "open-meteo"
    replay: bool = False


class SensorReading(BaseModel):
    """One reading from a village gauge. simulated=True for scripts/gauge_sim.py, never real hardware."""

    village_id: str
    device_id: str
    at: str
    water_level_cm: float
    rain_mm_1h: float | None = None
    battery_v: float | None = None
    rssi: int | None = None
    simulated: bool = False
    received_at: str | None = None
    # How it arrived: a signed HTTPS POST, or MQTT over AWS IoT Core (X.509 per device).
    transport: Literal["https", "mqtt"] = "https"


class ReportScreen(BaseModel):
    """What the guardrail said about a report's words (llm/guardrail.py)."""

    allowed: bool = True
    action: str = "NONE"
    reasons: list[str] = Field(default_factory=list)
    engine: Literal["bedrock-guardrail", "local-heuristic"] = "local-heuristic"
    at: str = ""
    field: Literal["text", "transcript"] = "text"


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
    # None on reports made before screening existed, or with no words to screen.
    screen: ReportScreen | None = None
    masked_text: str | None = None  # the screened words with phone numbers and e-mails masked

    @property
    def held(self) -> bool:
        """Held for review: the guardrail stopped the words; only an officer can verify it."""
        return self.screen is not None and not self.screen.allowed


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


class ChecklistItem(BaseModel):
    """One early-action task for a village (services/checklist.py)."""

    village_id: str
    item: str
    label_en: str
    label_hi: str
    order: int = 0
    done: bool = False
    done_by: str | None = None
    done_at: str | None = None


class Directive(BaseModel):
    id: str
    village_id: str
    type: DirectiveType
    text_hi: str
    text_en: str
    issued_by: str
    issued_at: str
    active: bool = True


class ShelterStatus(BaseModel):
    """The shelter ledger: what a pradhan or officer last said about one safe place.

    place_id is a baked OpenStreetMap place (data/safe_places/); a place with no
    row has never been confirmed by anyone and is never named in an alert.
    """

    village_id: str
    place_id: str
    status: ShelterState
    capacity: int | None = None
    note: str = ""
    updated_by: str
    updated_at: str


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


RollCallAnswer = Literal["safe", "need_help"]


class RollCall(BaseModel):
    """A "Surakshit Hoon" (मैं सुरक्षित हूँ) safety roll-call for one village after an alert.

    exercise=True for drills (labelled as such everywhere). Replays never open one.
    Counts are kept on the record so the public page reads one item and no names.
    """

    id: str
    village_id: str
    village_name: str
    village_name_hi: str
    alert_id: str | None = None
    level: Level | None = None
    opened_at: str
    closes_at: str
    opened_by: Literal["system", "officer"] = "system"
    opened_by_user: str | None = None
    exercise: bool = False
    asked: int = 0
    safe: int = 0
    need_help: int = 0
    last_reminded_at: str | None = None
    reminders: int = 0


class RollCallAsked(BaseModel):
    """Who the question went to. channel "stub" is a demo recipient with no phone: nothing was sent."""

    rollcall_id: str
    recipient_id: str
    name: str
    channel: Literal["telegram", "stub"]
    asked_at: str
    reminded_at: str | None = None
    error: str | None = None


class RollCallResponse(BaseModel):
    rollcall_id: str
    recipient_id: str
    name: str
    status: RollCallAnswer
    at: str
    note: str | None = None  # optional free text (140 chars at most) sent after "need help"
    share_id: str | None = None  # opaque id behind the family link, so no chat id is in the link
    simulated: bool = False  # set only by tests and demo tooling for stub recipients, never by a real tap
