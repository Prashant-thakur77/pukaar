"""Domain records. Plain Pydantic models; the repo maps them to DynamoDB items."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

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
    # Where the three stage thresholds came from. Seeded values are illustrative; an officer can
    # replace them with a proposal learned from the gauge's own record (services/gauge_learn.py).
    thresholds_source: str = "seeded (illustrative)"
    thresholds_set_by: str | None = None
    thresholds_set_at: str | None = None


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
    # The newest alert raised for this village (kept after it closes): a declined or expired alert
    # is asked again while the level holds (decision_engine.reask_due).
    last_alert_id: str | None = None
    # Live villages: always False. A replay works on its own copy (repo REPLAY / VILLAGE#id), so
    # starting, running or resetting a replay never changes the live record.
    replay: bool = False
    # Data freshness (decision_engine.note_data): "ok" when the last sweep had complete forecast
    # data; "stale" while the last complete values are carried forward (at most
    # Settings.stale_max_sweeps sweeps); "unavailable" after that. A stale or unavailable sweep
    # never counts as a calm sweep, so missing data never walks a level down to normal.
    data_status: Literal["ok", "stale", "unavailable"] = "ok"
    data_ok_at: str | None = None  # time of the last sweep with complete data
    data_missing_sweeps: int = 0
    data_note: str = ""


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
    # What the provider left out (e.g. "rain", "discharge"): unknown, never read as 0.
    missing: list[str] = Field(default_factory=list)
    # Set on the copy the rules used when the last complete values were carried forward.
    carried_from: str | None = None


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


class StaffPoint(BaseModel):
    """A point on the reference photo, in normalised image coordinates (0..1, origin top left)."""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class StaffMark(BaseModel):
    """One mark on a virtual staff gauge: a CrowdWater-style class ("+3") or a height ("150 cm")."""

    label: str = Field(min_length=1, max_length=12)
    value: float = Field(ge=-1000, le=5000)  # orders the marks: class number or height in cm
    height_cm: float | None = Field(default=None, ge=-1000, le=5000)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class StaffGauge(BaseModel):
    """A virtual staff gauge (CrowdWater pattern): a reference photo of a fixed object by the khad
    with a scale drawn on it once. Later photos from the same spot are read against the scale.

    watch_at / warning_at / critical_at: mark values at or above which an officer-confirmed reading
    means that level (services/staff_gauge.py). None: the reading is an observation only.
    """

    id: str
    village_id: str
    name: str = Field(min_length=1, max_length=80)
    name_hi: str = Field(default="", max_length=80)
    where: str = Field(default="", max_length=200)  # how to find the spot and where to stand
    photo_key: str
    scale_top: StaffPoint
    scale_bottom: StaffPoint
    unit: Literal["class", "cm"] = "class"
    marks: list[StaffMark]
    watch_at: float | None = None
    warning_at: float | None = None
    critical_at: float | None = None
    active: bool = True
    created_by: str
    created_at: str
    updated_by: str | None = None
    updated_at: str | None = None


StaffStatus = Literal["unconfirmed", "confirmed", "unreadable"]


class StaffReading(BaseModel):
    """The mark a villager chose against a staff gauge, and what an officer made of it."""

    gauge_id: str
    gauge_name: str = ""
    mark: str  # label the villager tapped
    value: float
    height_cm: float | None = None
    chosen_at: str
    status: StaffStatus = "unconfirmed"
    confirmed_mark: str | None = None
    confirmed_value: float | None = None
    confirmed_height_cm: float | None = None
    # Level of the confirmed mark against the gauge's configured marks, fixed at confirmation.
    confirmed_level: Level | None = None
    confirmed_by: str | None = None
    confirmed_at: str | None = None


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
    # "Compare with the marked rock": the mark the villager chose on a staff gauge (services/staff_gauge.py).
    staff_reading: StaffReading | None = None

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
    # Voice: the 8 kHz call audio (voice/polly.synthesize_call_audio), and how many re-send rounds ran.
    call_audio_key: str | None = None
    recall_rounds: int = 0


E164 = re.compile(r"^\+[1-9]\d{7,14}$")
VOICE_CHANNELS = {"voice", "both"}
TELEGRAM_CHANNELS = {"telegram", "both"}


class Recipient(BaseModel):
    # A Telegram chat id ("both": the chat id of someone who also takes calls), "stub-..." for demo
    # recipients, or "v_<ulid>" for someone reached by voice call only (scripts/voice.py).
    id: str
    village_id: str
    name: str
    role: Literal["villager", "pradhan", "officer"] = "villager"
    # "stub" only for demo recipients with no phone. A telegram or voice recipient is never quietly
    # sent to the stub: if the channel cannot be reached the delivery is recorded as failed (dispatch.py).
    channel: Literal["telegram", "voice", "both", "stub"] = "telegram"
    # E.164 (+91XXXXXXXXXX), for voice and both only. Stored like the Telegram chat id (the table is
    # encrypted at rest), never on a public route, never written to a log (voice.mask).
    phone: str | None = None
    # How and when the household agreed to be called (voice and both), e.g. "verbal, field visit 2026-10-25".
    consent: str | None = None
    language: str = "hi"

    @field_validator("phone")
    @classmethod
    def _e164(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        v = v.strip().replace(" ", "").replace("-", "")
        if not E164.match(v):
            raise ValueError("phone must be in E.164 form, e.g. +919812345678")
        return v

    @model_validator(mode="after")
    def _voice_needs_phone(self) -> "Recipient":
        if self.channel in VOICE_CHANNELS and not self.phone:
            raise ValueError(f"a {self.channel} recipient needs a phone number")
        return self

    @property
    def takes_voice(self) -> bool:
        return self.channel in VOICE_CHANNELS

    @property
    def takes_telegram(self) -> bool:
        return self.channel in TELEGRAM_CHANNELS


VoiceCategory = Literal["busy", "no_answer", "failed", "no_status", "invalid_number", "machine", "no_key",
                        "provider_error", "provider_off", "blocked"]


class Delivery(BaseModel):
    """One send of one alert to one person on one channel. A "both" recipient has two rows.

    Voice rows: status "pending" while the call is placed but not answered, "sent" once answered
    (sent_at is the first answer: the voice reached the ear), "failed" when not connected or not
    placed, "acknowledged" after a key press (1, or 2 for help). Two retry counters (docs/VOICE.md):
    not_connected (busy, no answer, failed) and no_key (answered, no valid key).
    """

    alert_id: str
    recipient_id: str
    name: str
    channel: str
    status: Literal["pending", "sent", "failed", "acknowledged"] = "pending"
    sent_at: str | None = None
    attempts: int = 0
    acknowledged_at: str | None = None
    error: str | None = None
    # -- voice only
    provider: str | None = None  # exotel | plivo | stub (replay only, no call placed)
    call_ids: list[str] = Field(default_factory=list)  # provider call id per attempt, oldest first
    call_status: str | None = None  # queued | ringing | answered | completed | busy | no_answer | failed | simulated
    last_attempt_at: str | None = None
    not_connected: int = 0
    no_key: int = 0
    error_category: VoiceCategory | None = None
    digit: str | None = None  # the last valid key pressed: 1 heard, 2 needs help, 3 repeat
    repeats: int = 0
    reprompts: int = 0
    unreachable: bool = False  # terminally: flagged to the pradhan and on the alert timeline

    @property
    def row_key(self) -> str:
        return delivery_key(self.recipient_id, self.channel)


def delivery_key(recipient_id: str, channel: str) -> str:
    """The sort-key suffix: voice rows sit beside the person's Telegram row."""
    return f"{recipient_id}#voice" if channel == "voice" else recipient_id


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


class RoadBlock(BaseModel):
    """A road or path that a pradhan or officer says is blocked, at one point on a baked route.

    Routes are baked offline, so a block never creates a new route: every baked
    route passing within ROADBLOCK_RADIUS_M of the point counts as blocked, and the
    next baked route is promoted. Lapses after 7 days unless someone renews it.
    """

    id: str
    village_id: str
    lat: float
    lon: float
    label: str = ""  # the road or bridge, as the person named it (optional)
    note: str
    created_by: str
    created_at: str
    renewed_by: str | None = None
    renewed_at: str | None = None
    expires_at: str
    cleared_by: str | None = None
    cleared_at: str | None = None


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
    """Who the question went to. channel "stub" is a demo recipient with no phone: nothing was sent.
    channel "voice": a voice-only recipient; the roll-call is not asked by call yet (error says so)."""

    rollcall_id: str
    recipient_id: str
    name: str
    channel: Literal["telegram", "voice", "stub"]
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


class PushSubscription(BaseModel):
    """A browser's Web Push subscription for one signed-in officer or pradhan (services/officer_push.py).

    id is derived from the endpoint, so the same browser subscribing again replaces its own row.
    """

    id: str
    username: str
    endpoint: str
    p256dh: str  # the browser's P-256 public key, base64url
    auth: str  # the browser's 16-byte auth secret, base64url
    created_at: str
    user_agent: str = ""  # a short summary such as "Chrome on Android", never the full header
    last_sent_at: str | None = None
