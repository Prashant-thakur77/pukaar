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
# "Was this real?": what an officer records after an alert closed (api/routers/officer.py). It feeds the
# false-alarm rate per rule on /public/pilot-metrics.
AlertOutcome = Literal["real_flood", "no_flood", "unknown"]
ALERT_OUTCOMES: tuple[str, ...] = ("real_flood", "no_flood", "unknown")

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
    """River discharge thresholds (m³/s) for the village's river cell (scripts/calibrate.py).

    method "return_period": watch, warning, critical = the 2-, 5- and 20-year discharges of a
    Gumbel fit to annual maxima. cell_lat/cell_lon: the GloFAS cell the live sweep asks for (the
    village's own coordinates when unset); cell_verified is False until the cell is checked to be
    on the stream that floods the village (data/river_cells.json).

    early: the "get ready" line (`early_cms` in data/thresholds.json), the 90th percentile of daily
    discharge at the same cell, i.e. the old Watch line. Only the readiness outlook reads it
    (services/readiness.py); it never sets a level, never creates an alert and never sends.
    """

    watch: float
    warning: float
    critical: float
    source: str = "open-meteo flood API daily history 1997-2024 (requested from 1984; the archive starts in 1997 here)"
    method: str = "percentile"
    return_period_years: dict[str, int] | None = None
    cell_lat: float | None = None
    cell_lon: float | None = None
    river: str | None = None
    cell_verified: bool = False
    early: float | None = None

    @classmethod
    def from_file(cls, entry: dict[str, Any]) -> "Thresholds":
        """One village's entry of data/thresholds.json."""
        cell = entry.get("river_cell") or {}
        return cls(watch=entry["watch"], warning=entry["warning"], critical=entry["critical"],
                   source=entry.get("source", ""), method=entry.get("method", "percentile"),
                   return_period_years=entry.get("return_period_years"),
                   cell_lat=cell.get("lat"), cell_lon=cell.get("lon"), river=entry.get("river"),
                   cell_verified=bool(entry.get("cell_verified", False)), early=entry.get("early_cms"))


class SoilRange(BaseModel):
    """The village's own root-zone soil moisture range (m³/m³): dry = 5th, wet = 95th percentile.

    Saturation S = (sm - dry) / (wet - dry), clipped to 0..1 (services/soil.py).
    """

    dry: float
    wet: float
    source: str = "default"


class RainGaugeConfig(BaseModel):
    """A tipping-bucket rain gauge on a river gauge (v3) or a rain-only node (services/rain_obs.py).

    The bands are ILLUSTRATIVE: calibrate them per khad with IMD and HPSDMA before relying on them
    (Nepal's Birendranagar rain siren uses 60 mm/h). Observed rain alone never goes above Warning.
    """

    mm_per_tip: float = Field(default=0.2, gt=0, le=2)
    # Intensity correction for the water lost while the bucket tips: mm x (1 + c x max(0, I - i0)).
    correction_c: float = Field(default=0.0005, ge=0, le=0.01)
    i0_mm_h: float = 50.0
    max_plausible_mm_h: float = 300.0  # a 5-minute rate above this is chatter, not rain
    min_tip_ms: int = 400
    watch_15min: float = 10.0
    watch_1h: float = 15.0
    watch_3h: float = 40.0
    warning_15min: float = 20.0
    warning_1h: float = 30.0
    warning_3h: float = 70.0
    installed: bool = False
    thresholds_source: str = "illustrative; calibrate per khad with IMD/HPSDMA"


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
    # The datum, kept on the server (services/gauge.py): the sensor face's height above the gauge
    # zero, measured with a tape at installation. With it, a payload-v2 raw distance becomes the
    # stage here, so a firmware bug or a wrong constant on the device cannot shift the stage.
    mount_height_cm: float | None = None
    # ultrasonic: the speed of sound is corrected for temp_c; radar (e.g. DFRobot SEN0676): no correction.
    sensor: Literal["ultrasonic", "radar"] = "ultrasonic"
    # A distance at or inside the blind zone, or at or beyond the maximum range, is out_of_range.
    blind_zone_mm: float = 250.0
    max_range_mm: float = 4500.0
    # False-alarm guard: a change faster than this (cm per minute) is a spike and is not counted.
    max_rise_cm_per_min: float = 30.0
    # Rate of rise: at least rise_cm over rise_minutes, across 3 or more good readings, is "rising fast".
    rise_cm: float = 30.0
    rise_minutes: float = 30.0
    # Health: a battery under this is low (3500 mV suits one Li-ion cell; use about 3100 for LiFePO4).
    low_battery_mv: float = 3500.0
    # Gauge v3 / rain node: the tipping bucket's calibration and the observed-rain bands (rain_obs).
    rain: RainGaugeConfig | None = None


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
    # From data/districts.json and data/villages.json at seed time, never from code (services/cap.py):
    # the district's Hindi name and its Local Government Directory (LGD) code, and the village's LGD
    # code when one was verified. None: not known, and the CAP message carries no such geocode.
    district_hi: str | None = None
    lgd_district_code: str | None = None
    lgd_village_code: str | None = None
    # The number a caller keys in on the enrolment IVR to pick this village (delivery/inbound.py): from
    # data/villages.json ("ivr_code") at seed time, printed on the village card. None: not reachable by keypad.
    ivr_code: str | None = None
    # Households on the village list (from the pradhan and patwari): the denominator of coverage (pilot metric 1).
    # None until the list is received; coverage is then "not measured", never guessed.
    households: int | None = None
    # The live jury demo's own village (services/demo.py): never in the village registry, so never in a list,
    # the sweep, the CAP feed, SACHET, the counters or the pilot metrics; Repo.get_village hides it unless asked.
    demo: bool = False


class Reading(BaseModel):
    village_id: str
    at: str
    rain_24h_mm: float | None = None
    rain_hourly: list[dict[str, Any]] = Field(default_factory=list)
    # The same hours from the other forecast models the heavy-burst rule reads (PUKAAR_RAIN_MODELS),
    # {model: [{"t", "mm"}]}; rain_hourly is best_match and alone gives the 24-hour sum.
    rain_models: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
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
    # GloFAS ensemble river forecast for the river cell, fetched once a day (external_data.ensemble):
    # status ok|unavailable|off, and per lead day the sorted member discharges.
    discharge_ensemble: dict[str, Any] | None = None
    # Official data shown beside the level (services/official_data.py): one item per source.
    official: list[dict[str, Any]] = Field(default_factory=list)


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
    # live: sent as it was measured. backfill: sent later from the device's buffer; stored and
    # shown, never counted by the rules and never a trigger (services/gauge.py).
    origin: Literal["live", "backfill"] = "live"
    # Set at ingest (services/gauge.py). Only "good" readings count toward a level.
    quality: Literal["good", "suspect", "spike", "out_of_range"] = "good"
    quality_reasons: list[str] = Field(default_factory=list)
    measured_level: str | None = None  # this reading's stage band on its own
    confirmed_level: str | None = None  # 2 of the last 3 good live readings at or above
    rising_fast: bool = False
    rise_cm: float | None = None  # rise across the rate-of-rise window, when rising fast
    effective_level: str | None = None  # what the rules count: confirmed, one step up if rising fast
    # Payload v2 (docs/hardware/README.md), stored as sent.
    schema_version: int = 1
    seq: int | None = None
    boot: int | None = None
    distance_mm: float | None = None
    samples_ok: int | None = None
    samples_n: int | None = None
    iqr_mm: float | None = None
    device_quality: int | None = None
    err: int | None = None
    temp_c: float | None = None
    solar_mv: float | None = None
    fw: str | None = None
    reset_cause: str | None = None
    buffered: bool = False
    # Payload v3 (gauge v3 and rain nodes): the tipping bucket, stored as sent.
    rain_tips_total: int | None = None
    rain_tips_window: int | None = None
    rain_mm_per_tip: float | None = None
    rain_max_tips_1min: int | None = None
    rain_min_tip_ms: int | None = None
    rain_bounce: int | None = None
    rain_err: int | None = None


class RainReading(BaseModel):
    """One observed-rain reading (VILLAGE#<v> / RAIN#<iso>#<device>) from a gauge v3's tipping bucket or a
    rain-only node, with what services/rain_obs.py made of it at ingest.

    mm_raw: this reading's rain (the counter difference times the server's mm_per_tip); mm: corrected for
    the water a bucket loses while it tips at high intensity. windows: the corrected 15 min, 1 h and 3 h
    totals ending at this reading (live, good readings only). eval_level: the band those windows reach;
    confirmed_level: a band reached in 2 of the last 3 evaluations. quality "suspect" never counts."""

    village_id: str
    device_id: str
    at: str
    source: Literal["gauge", "rain_node"] = "gauge"
    origin: Literal["live", "backfill"] = "live"
    simulated: bool = False
    received_at: str | None = None
    transport: Literal["https", "mqtt"] = "mqtt"
    seq: int | None = None
    boot: int | None = None
    tips_total: int | None = None
    tips_window: int | None = None
    device_mm_per_tip: float | None = None  # what the device says; the server's calibration is used
    max_tips_1min: int | None = None
    min_tip_ms: int | None = None
    bounce: int | None = None
    err: int | None = None
    battery_v: float | None = None
    rssi: int | None = None
    fw: str | None = None
    tips: int = 0
    minutes: float = 5.0
    mm_raw: float = 0.0
    mm: float = 0.0
    rate_mm_h: float = 0.0
    quality: Literal["good", "suspect"] = "good"
    quality_reasons: list[str] = Field(default_factory=list)
    windows: dict[str, float] = Field(default_factory=dict)
    eval_level: str = "normal"
    confirmed_level: str = "normal"


class ReportScreen(BaseModel):
    """What the guardrail said about a report's words (llm/guardrail.py)."""

    allowed: bool = True
    action: str = "NONE"
    reasons: list[str] = Field(default_factory=list)
    engine: Literal["bedrock-guardrail", "local-heuristic"] = "local-heuristic"
    at: str = ""
    field: Literal["text", "transcript"] = "text"


class ReportSource(BaseModel):
    """Where a report came from, as salted hashes only (services/report_guard.py). Never a raw IP.

    ip: the client address; net: its /24 (IPv4) or /64 (IPv6); device and session: the random ids the
    report page keeps in localStorage and sessionStorage. None means it was not sent or the salt was
    unreadable, and an unknown source can never corroborate another report.
    """

    ip: str | None = None
    net: str | None = None
    device: str | None = None
    session: str | None = None


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
    # Report-abuse protection (services/report_guard.py): salted source hashes (never shown, never public)
    # and why the report is held for an officer when it came in over a rate limit.
    source: ReportSource | None = None
    hold_reason: str | None = None  # "source_rate_limit" | "village_surge"

    @property
    def held(self) -> bool:
        """Held for review: the guardrail stopped the words, or the report came in over a rate limit.
        Kept and shown to officers; only an officer can verify it."""
        return (self.screen is not None and not self.screen.allowed) or bool(self.hold_reason)


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
    # Counted in people, each once, by an atomic ADD with a per-person marker (Repo.mark_person):
    # delivered_count  everyone reached, the demo stub channel included (a replay reaches only the stub)
    # phones_reached_count  of them, people reached on a real phone (Telegram, or a call answered); never the stub
    # acknowledged_count  people who pressed "मिल गया" (or 1 on a call)
    delivered_count: int = 0
    acknowledged_count: int = 0
    phones_reached_count: int = 0
    district: str = ""  # the village's district when the alert was made: the inbox filters by it
    audio_key: str | None = None
    task_token: str | None = None
    token_version: int = 0
    execution_arn: str | None = None
    replay: bool = False
    # Voice: the 8 kHz call audio (voice/polly.synthesize_call_audio), and how many re-send rounds ran.
    call_audio_key: str | None = None
    recall_rounds: int = 0
    # Who is asked, in order, frozen when the alert is drafted (services/roster.py): the duty roster's
    # primary, backup and escalation officer (ADM or DM) for the shift on duty then, or the village's
    # fallback list when the district has no roster for that shift. officer_chain_roles says which is which.
    officer_chain: list[str] = Field(default_factory=list)
    officer_chain_roles: list[str] = Field(default_factory=list)
    officers_asked: list[str] = Field(default_factory=list)  # everyone asked or reminded, for the all-clear
    nudges: int = 0  # reminders sent half-way through an officer's approval window
    # Nobody in the chain answered (workflow/steps.step_unanswered): when the last call went to every
    # rostered officer and the ADM or DM, each with a fresh one-tap link, and AlertUnanswered was emitted.
    unanswered_at: str | None = None
    # The asked officer opened the one-tap approval link (api/routers/public.approval_view) for this
    # token_version: the wake-up call at the nudge is not placed (delivery/officer_call.py).
    approval_opened_by: str | None = None
    approval_opened_at: str | None = None
    approval_opened_version: int | None = None
    # The all-clear (workflow/steps.stand_down): when the alert was stood down, by whom and why, and how
    # many people and officers it reached or failed to reach. Set once.
    all_clear_at: str | None = None
    all_clear_by: str | None = None
    all_clear_reason: str | None = None
    all_clear_sent: int = 0
    all_clear_failed: int = 0
    # "Was this real?", set by an officer after the alert closed; who and when go to the audit trail too.
    outcome: AlertOutcome | None = None
    outcome_by: str | None = None
    outcome_at: str | None = None
    # The siren tier (services/sirens.py), kept apart from people: commanded, started (the device said
    # so), verified (current and microphone evidence). Never counted in delivered or acknowledged.
    sirens_total: int = 0
    sirens_started: int = 0
    sirens_verified: int = 0
    siren_first_started_at: str | None = None
    siren_first_verified_at: str | None = None
    siren_pattern: str | None = None
    siren_note: str | None = None
    # When harm began, if the officer recording "was this real?" knows it (metric 5, lead time achieved).
    outcome_onset_at: str | None = None
    # The "why we warned" note (services/followup.py): once per alert, after it ends. trigger: outcome, all_clear
    # or expired. sent/failed/skipped count people.
    followup_at: str | None = None
    followup_trigger: str | None = None
    followup_sent: int = 0
    followup_failed: int = 0
    followup_skipped: int = 0


E164 =re.compile(r"^\+[1-9]\d{7,14}$")
VOICE_CHANNELS = {"voice", "both"}
TELEGRAM_CHANNELS = {"telegram", "both"}
# Village relays (the Practical Action "cascade" pattern): the pradhan, the gauge reader and the task-force
# volunteers are contacted first, so the siren and the megaphone start while the other phones still ring.
RELAY_ROLES = {"pradhan", "gauge_reader", "task_force"}
RecipientRole = Literal["villager", "pradhan", "gauge_reader", "task_force", "officer"]


class Recipient(BaseModel):
    # A Telegram chat id ("both": the chat id of someone who also takes calls), "stub-..." for demo
    # recipients, or "v_<ulid>" for someone reached by voice call only (scripts/voice.py).
    id: str
    village_id: str
    name: str
    role: RecipientRole = "villager"
    # "stub" only for demo recipients with no phone. A telegram or voice recipient is never quietly
    # sent to the stub: if the channel cannot be reached the delivery is recorded as failed (dispatch.py).
    channel: Literal["telegram", "voice", "both", "stub"] = "telegram"
    # E.164 (+91XXXXXXXXXX), for voice and both only. Stored like the Telegram chat id (the table is
    # encrypted at rest), never on a public route, never written to a log (voice.mask).
    phone: str | None = None
    # How and when the household agreed to be called (voice and both), e.g. "verbal, field visit 2026-10-25".
    consent: str | None = None
    language: str = "hi"
    # Assisted household (elderly, disabled, no phone of their own): someone in the village checks on them
    # in person. Shared with the assisted-households work; the enrolment form sets it (services/enrolment.py).
    assisted: bool = False
    # How the person was enrolled (services/enrolment.py): "telegram", "form", "csv" or "ivr", and by whom
    # (an officer's or pradhan's username, or "self" for the caller on the IVR).
    enrolled_via: str | None = None
    enrolled_by: str | None = None
    # An assisted household (older, disabled, living alone, pregnant): if they have not confirmed an alert within
    # PUKAAR_ASSISTED_ESCALATE_MINUTES, the named neighbour or relay (escalate_to, a recipient of the same village;
    # else the village's relays) is asked to check on them (services/assisted.py). Set by an officer or the pradhan.
    assisted_reason: Literal["elderly", "disabled", "alone", "pregnant", "other"] | None = None
    escalate_to: str | None = None
    # Optional, and only to report coverage (half the observers and relays women, as in Bangladesh's CPP).
    # Never used to decide who is warned or in what order.
    gender: Literal["female", "male", "other"] | None = None
    # When the person joined (the live jury demo: services/demo.py erases its people 24 hours after this).
    joined_at: str | None = None

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

    @property
    def is_relay(self) -> bool:
        return self.role in RELAY_ROLES


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
    # -- the all-clear on this row's channel (workflow/steps.stand_down)
    all_clear_status: Literal["sent", "failed", "stub"] | None = None
    all_clear_at: str | None = None
    all_clear_error: str | None = None
    all_clear_call_id: str | None = None  # voice: the all-clear call; it has no menu and moves no counter
    # -- delivery at scale (dispatch.py): which send round claimed this row last (0 the first delivery,
    # 1.. the re-sends, -1 the failsafe), so one row is sent at most once per round however many batch
    # workers or retries touch it; deferred: put back unsent (Telegram 429 or out of time), sent next pass.
    send_round: int | None = None
    deferred: bool = False
    # Erasure (services/privacy.py): the person left and their name, chat id and call ids were removed;
    # recipient_id is then a pseudonym and the row keeps only channel, status, attempts and times.
    erased: bool = False
    # -- an assisted household not confirmed in time (services/assisted.py): who was asked to check, and when they
    # pressed "देख लिया" (checked). Set once each, by conditional writes.
    escalated_at: str | None = None
    escalated_to: str | None = None
    escalation_error: str | None = None
    checked_at: str | None = None
    checked_by: str | None = None

    @property
    def row_key(self) -> str:
        return delivery_key(self.recipient_id, self.channel)


def delivery_key(recipient_id: str, channel: str) -> str:
    """The sort-key suffix: voice rows sit beside the person's Telegram row."""
    return f"{recipient_id}#voice" if channel == "voice" else recipient_id


class OfficerCall(BaseModel):
    """The wake-up call to an officer who has not opened an approval (delivery/officer_call.py).

    One per officer per alert. It never approves: "1" only sends the one-tap approval link again
    to the officer's Telegram and Web Push; the approval itself stays a deliberate tap in the app.
    status: placed (the provider took the call), not_possible (voice off, no phone, a replay),
    failed (the provider refused it), answered, completed, not_connected, link_sent.
    """

    alert_id: str
    officer: str
    officer_index: int = 0
    level: str = ""
    status: Literal["placing", "placed", "not_possible", "failed", "answered", "completed", "not_connected",
                    "link_sent"] = "placing"
    reason: str | None = None
    provider: str | None = None
    call_id: str | None = None
    call_status: str | None = None
    placed_at: str | None = None
    answered_at: str | None = None
    digit: str | None = None
    link_sent_at: str | None = None
    link_channels: list[str] = Field(default_factory=list)


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


ShiftId = Literal["day", "night"]
EscalationTitle = Literal["ADM", "DM"]


class RosterShift(BaseModel):
    """One shift of a district's duty roster (services/roster.py). Times are IST.

    date is the IST date the shift starts: "night" on 22 Oct runs from 20:00 on 22 Oct to 08:00 on
    23 Oct. The approval chain is the primary, then the backup, then the escalation officer above
    them (the ADM or the DM).
    """

    district: str
    date: str  # YYYY-MM-DD, IST
    shift: ShiftId
    primary: str
    backup: str | None = None
    escalation: str | None = None
    escalation_title: EscalationTitle = "ADM"
    note: str = ""
    updated_by: str
    updated_at: str
    # Handover: who took this shift over from whom, and when (the audit trail has it too).
    taken_over_from: str | None = None
    taken_over_at: str | None = None


class HandoverNote(BaseModel):
    """The shift handover (services/duty.py): the outgoing officer writes what the next shift must know, the
    incoming officer acknowledges it. One per district shift; both steps are in the audit trail."""

    district: str
    date: str  # the IST date of the shift the note is written in (the outgoing shift)
    shift: ShiftId
    text: str
    written_by: str
    written_at: str
    # The next shift, when the note was written: who is expected to acknowledge it.
    for_date: str
    for_shift: ShiftId
    acknowledged_by: str | None = None
    acknowledged_at: str | None = None


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


# -- the alarm layer's devices (services/devices, services/sirens.py) ------------------------------
DeviceKind = Literal["siren", "gauge", "box", "relay", "rain"]
DEVICE_KINDS: tuple[str, ...] = ("siren", "gauge", "box", "relay", "rain")
DeviceHealth = Literal["ok", "degraded", "offline", "fault", "unknown"]


class Device(BaseModel):
    """One device in the registry (VILLAGE#<v> / DEVICE#<d>): placement, configuration and live health.

    Nothing secret is kept here: keys are derived when needed (services/devices/keys.py). sim_number is
    the siren SIM's phone number for the officer's SMS fallback; it is never on a public view.
    """

    device_id: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    village_id: str
    kind: DeviceKind
    installed: bool = False
    simulated: bool = False
    hw_rev: str | None = None
    fw: str | None = None
    lat: float | None = None
    lon: float | None = None
    horn_azimuth_deg: float | None = None
    coverage_m: float | None = None  # measured at acceptance (SPL >= ambient + 10 dB at the farthest house)
    voice_slot: int = 0
    owner_recipient_id: str | None = None  # a box: the pradhan's recipient row ("मिल गया" acknowledges it)
    lora_addr: int | None = Field(default=None, ge=0, le=0xFFFE)
    kid: int = 1
    allowed_senders: list[str] = Field(default_factory=list)
    test_schedule: str = "SUN 11:00"
    autonomy: dict[str, Any] = Field(default_factory=lambda: {"enabled": False, "fast_path": False,
                                                              "shadow_mode": True})
    amp_a_ref: float = 3.3
    siren_a_ref: float = 1.5
    spl_rise_min_db: float = 15.0
    sim_number: str | None = None
    note: str = ""
    # -- live health, from heartbeats, events and presence (services/devices/registry.py)
    last_seen: str | None = None
    last_seen_path: Literal["cell", "lora", "sms"] | None = None
    connected: bool | None = None
    conn_version: int | None = None
    state: str | None = None  # the device's own: idle, sounding, testing, manual, autonomous, fault, low_power
    state_since: str | None = None
    soc: int | None = None
    batt_mv: int | None = None
    solar_wh_today: float | None = None
    rssi: int | None = None
    lora_noise_dbm: int | None = None
    temp_c: float | None = None
    outbox_depth: int | None = None
    faults: list[str] = Field(default_factory=list)
    last_test_silent: dict[str, Any] | None = None  # {at, ok, detail}
    last_test_audible: dict[str, Any] | None = None  # {at, ok, amp_a, spl_rise_db}
    last_sound: dict[str, Any] | None = None  # {alert_id, at, pattern, verified}
    tamper_at: str | None = None
    pending_cmd: dict[str, Any] | None = None  # {cmd_id, pattern, at, state, alert_id}
    pour_test_until: str | None = None
    created_at: str | None = None
    # Battery history for the FloodNet-style slope (services/devices/floodnet.py): [{at, mv?, soc?}], one point an
    # hour at most from heartbeats, a week kept. Gauges and rain nodes need none: their readings carry it.
    batt_hist: list[dict[str, Any]] = Field(default_factory=list)


CommandState = Literal["commanded", "started", "verified", "not_confirmed", "expired", "rejected", "stopped",
                       "finished", "failed"]


class SirenCommand(BaseModel):
    """A signed command as issued (DEVICE#<d> / CMD#<id>), without its signature."""

    id: str
    device_id: str
    village_id: str
    action: Literal["sound", "stop", "test"]
    pattern: str | None = None
    clip: str | None = None
    clip_sha256_16: str | None = None
    level: str | None = None
    alert_id: str | None = None
    cycles: int = 0
    repeat_every_s: int = 0
    repeat_cycles: int = 0
    cap_on_s: int = 0
    volume: int = 0
    iat: int
    exp: int
    ctr: int
    src: str
    kid: int = 1
    round: int = 0
    by: str = "system"
    simulated: bool = False
    state: CommandState = "commanded"
    via: str | None = None
    commanded_at: str
    started_at: str | None = None
    verified_at: str | None = None
    meas: dict[str, Any] | None = None
    reason: str | None = None


SirenRowStatus = Literal["commanded", "started", "verified", "not_confirmed", "rejected", "failed", "skipped"]


class SirenDelivery(BaseModel):
    """The siren tier of one alert (ALERT#<id> / SIREN#<device>#<round>): kept apart from the people
    rows, so it is never counted as a person reached, re-sent to, or told the all-clear by phone."""

    alert_id: str
    device_id: str
    village_id: str
    round: int = 0
    cmd_id: str | None = None
    pattern: str | None = None
    level: str | None = None
    src: str = "approval"
    status: SirenRowStatus = "commanded"
    commanded_at: str | None = None
    started_at: str | None = None
    verified_at: str | None = None
    meas: dict[str, Any] | None = None
    error: str | None = None
    simulated: bool = False


class SirenRequest(BaseModel):
    """Two-person rule (SIRENREQ#<id>): a Critical sounded by hand, or a Critical alert without machine
    evidence, needs a second, different officer within 120 s."""

    id: str
    village_id: str
    level: Literal["warning", "critical"]
    reason: str = ""
    requested_by: str
    requested_at: str
    expires_at: str
    alert_id: str | None = None
    confirmed_by: str | None = None
    confirmed_at: str | None = None
    status: Literal["open", "confirmed", "expired"] = "open"
