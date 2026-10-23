"""Settings read from PUKAAR_* environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _repo_data_dir() -> Path:
    # backend/src/Pukaar/core/config.py -> repo root is parents[4]
    return Path(__file__).resolve().parents[4] / "data"


@dataclass(frozen=True)
class Settings:
    mode: str  # "aws" or "local"
    stage: str
    aws_region: str
    table_name: str
    bucket: str
    state_machine_arn: str
    worker_function: str
    bedrock_model_id: str
    bedrock_fallback_region: str
    llm_enabled: bool
    llm_timeout_seconds: float
    transcribe_language: str
    polly_voice: str
    approval_timeout_seconds: int
    ack_wait_seconds: int
    replay_enabled: bool
    data_dir: Path
    web_url: str
    api_url: str
    ssm_prefix: str
    hydromet_enabled: bool
    hydromet_timeout_seconds: float
    alerts_per_village_per_day: int
    soil_modifier_enabled: bool
    cors_origins: tuple[str, ...]
    cognito_user_pool_id: str
    cognito_client_id: str
    cap_sender: str  # CAP <sender>: no spaces, commas, '<' or '&'
    guardrail_id: str = ""
    guardrail_version: str = ""
    guardrail_timeout_seconds: float = 8.0
    # After-action e-mail (services/after_action.py): the verified SES sender. Empty = no e-mail.
    ses_from: str = ""
    # AppSync Events HTTP domain (no scheme). Empty: live push is off and the web app polls.
    events_http_domain: str = ""
    # Missing forecast data (decision_engine.note_data): the last complete values are carried
    # forward for at most this many sweeps, then the village is marked "data unavailable".
    stale_max_sweeps: int = 4
    # A village with no complete forecast for this long emits VillageDataStale (alarmed).
    stale_alarm_minutes: int = 45
    # A declined or expired alert is asked again after this long if the level still holds, per level
    # (decision_engine.reask_due, reask_cooldown()). A Critical is asked again on the next sweep: its
    # cooldown is 0 to 5 minutes, never more, so nobody sleeps through one for a further half hour.
    reask_cooldown_critical_minutes: int = 5
    reask_cooldown_warning_minutes: int = 30
    reask_cooldown_watch_minutes: int = 60
    # Voice calls with "press 1" (delivery/voice.py): "exotel", "plivo" or "off". Off (the default)
    # records every voice delivery as failed with the reason; it never pretends a call went out.
    voice_provider: str = "off"
    # Attempts per voice recipient per alert, counting the first call (two retry counters share it).
    voice_max_attempts: int = 3
    voice_ring_timeout_seconds: int = 40
    # Exotel API host: api.exotel.com (Singapore cluster) or api.in.exotel.com (Mumbai cluster).
    exotel_api_host: str = "api.exotel.com"
    # A critical alert goes out with the fixed template when every officer in the chain timed out.
    # NEEDS DDMA SIGN-OFF: sending without a human decision is the DDMA's call, not Pukaar's. Off means
    # the alert expires unsent and the sweep asks again after the cooldown. Off unless set (template
    # parameter CriticalAutoSend; docs/DEPLOY.md "Production stage").
    critical_auto_send: bool = False
    # River trigger (risk_rules.river_assessment): a level is raised when at least this share of the
    # GloFAS ensemble members reach its return-period threshold on lead day 1-3 (the ECMWF reporting-
    # point convention is 0.3). The ensemble is fetched once a day per river cell (external_data).
    river_ensemble_enabled: bool = True
    river_ensemble_p_min: float = 0.3
    # Official corroboration (services/official_data.py): CWC stations above warning and the IMD
    # district warning colour are shown to officers; they raise a level only when
    # official_raises_level is on, and never lower one. Google Flood Hub needs an API key
    # (secret flood_hub_api_key) and BIPAD (Nepal) is optional: both off by default.
    official_data_enabled: bool = True
    official_raises_level: bool = False
    official_timeout_seconds: float = 5.0
    flood_hub_enabled: bool = False
    bipad_enabled: bool = False
    # Report-abuse protection (services/report_guard.py): reports per source (salted IP hash) and per
    # village in one window. A report over either limit is kept and held for an officer, never dropped.
    report_window_minutes: int = 10
    report_limit_per_source: int = 5
    report_limit_per_village: int = 30
    # Heavy-burst rule (risk_rules.rain_intensity): rolling 1/3/6-hour maxima of the hourly forecast.
    # rain_models: the Open-Meteo models asked in the same forecast request (best_match always first);
    # rain_models_combine: "max" (the highest model) or "mean" (the multi-model mean). docs/SCORING.md.
    rain_intensity_enabled: bool = True
    rain_models: tuple[str, ...] = ("best_match", "icon_seamless", "gfs_seamless")
    rain_models_combine: str = "max"
    # CAP <senderName> (services/cap.py), English and Hindi. Empty: the demo name, marked "(demo)". A
    # production stack must carry the issuing authority's own name (template parameter CapSenderName;
    # the deploy refuses an empty one for Stage=prod).
    cap_sender_name: str = ""
    cap_sender_name_hi: str = ""
    # DPDP: villager reports (words, transcript, GPS) expire this many days after they were made
    # (DynamoDB TTL), with their photo and voice note (S3 lifecycle, same parameter RetentionDays).
    # 0 keeps them until deleted by hand.
    report_retention_days: int = 0
    # Forecast readings and gauge readings are kept this many days (DynamoDB TTL; template parameter
    # ReadingRetentionDays): 30 on dev, 400 on prod, so a season's record can be reviewed after it.
    reading_retention_days: int = 30
    # Prod with CloudFront and AWS WAF in front of the API (template condition HasApiEdge): every request
    # must carry the origin-verify header CloudFront adds (main.py), so the WAF cannot be gone round.
    edge_required: bool = False
    # -- approval windows and the duty officer's wake-up call (workflow/steps.py) --
    # A critical alert's window per officer: shorter than approval_timeout_seconds, so a critical is not
    # held 20 to 30 minutes by a chain of three. Never longer than the general window.
    approval_timeout_critical_seconds: int = 300
    # The nudge (and the wake-up call to the duty officer, delivery/officer_call.py) comes this long into
    # an officer's window, or half-way through it if the window is shorter. 0 = half-way.
    officer_wake_seconds: int = 180
    # -- delivery at scale (delivery/dispatch.py, the Map state in infra/approval.asl.json) --
    delivery_batch_size: int = 250  # recipients per batch; the first batch is sent by the deliver step itself
    delivery_concurrency: int = 4  # batches at once (the Map's MaxConcurrency); each takes 1/n of the rate
    delivery_threads: int = 8  # sends in flight inside one batch
    delivery_budget_seconds: float = 200.0  # one step stops sending after this long; the rest is queued
    delivery_max_passes: int = 4  # a batch with queued sends is run again at most this many times in all
    telegram_rate_per_second: float = 25.0  # all chats together (Telegram allows about 30)
    telegram_chat_interval_seconds: float = 1.0  # one message per chat per second
    voice_calls_per_second: float = 2.0  # call requests to the voice provider, all batches together
    # -- the 15-minute sweep (services/decision_engine.sweep_all): villages evaluated at once --
    sweep_concurrency: int = 16
    # -- the alarm layer (services/sirens.py) --
    # Where siren commands go: "iot" (AWS IoT Core named shadows) or "local" (kept in the table).
    device_shadow: str = "local"
    # A command not verified this long after it was commanded is "not confirmed": the duty officer is told.
    siren_check_seconds: int = 180
    # Sound commands per village per hour (re-issues for the same alert not counted).
    siren_commands_per_village_per_hour: int = 6
    # Observed rain (services/rain_obs.py) may raise a level (never lower one; alone at most Warning).
    rain_obs_enabled: bool = True
    # -- scale (docs/CONTRACT.md, "At scale") --
    # /public/overview serves the counters the sweep stored while they are younger than this (one read
    # whatever the number of villages); 0 counts them on every request (local mode, tests).
    counters_max_age_seconds: int = 0
    # One Telegram budget for every Lambda (delivery/ratelimit.SharedBucket, DynamoDB): concurrent village
    # alerts share PUKAAR_TELEGRAM_RATE_PER_SECOND instead of each taking it. On by default on AWS.
    telegram_shared_limit: bool = False
    # -- DPDP (services/privacy.py, docs/SECURITY.md "DPDP") --
    # A person whose last village link went (/stop, बंद करें, a removal) keeps no number or chat id: what is
    # left of them (delivery rows, roll-call rows, their number in a report) is erased this many days later.
    # 0 erases at the next sweep. The recipient record itself is deleted at once.
    unlinked_retention_days: int = 30

    def reask_cooldown(self, level: str) -> int:
        """Minutes before an unsent alert at this level is asked again while the level holds."""
        if level == "critical":
            return self.reask_cooldown_critical_minutes
        if level == "watch":
            return self.reask_cooldown_watch_minutes
        return self.reask_cooldown_warning_minutes

    @property
    def guardrail_enabled(self) -> bool:
        return self.mode == "aws" and bool(self.guardrail_id and self.guardrail_version)

    @property
    def is_local(self) -> bool:
        return self.mode == "local"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    mode = os.environ.get("PUKAAR_MODE", "local").strip().lower()
    web_url = os.environ.get("PUKAAR_WEB_URL", "http://localhost:5173").rstrip("/")
    cors = os.environ.get("PUKAAR_CORS_ORIGINS", web_url)
    return Settings(
        mode=mode,
        stage=os.environ.get("PUKAAR_STAGE", "dev"),
        aws_region=os.environ.get("PUKAAR_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1")),
        table_name=os.environ.get("PUKAAR_TABLE_NAME", "pukaar-dev"),
        bucket=os.environ.get("PUKAAR_BUCKET", "pukaar-dev-local"),
        state_machine_arn=os.environ.get("PUKAAR_STATE_MACHINE_ARN", ""),
        worker_function=os.environ.get("PUKAAR_WORKER_FUNCTION", ""),
        bedrock_model_id=os.environ.get("PUKAAR_BEDROCK_MODEL_ID", "us.amazon.nova-2-lite-v1:0"),
        bedrock_fallback_region=os.environ.get("PUKAAR_BEDROCK_FALLBACK_REGION", "us-west-2"),
        llm_enabled=_bool("PUKAAR_LLM_ENABLED", mode == "aws"),
        llm_timeout_seconds=float(os.environ.get("PUKAAR_LLM_TIMEOUT_SECONDS", "20")),
        transcribe_language=os.environ.get("PUKAAR_TRANSCRIBE_LANGUAGE", "hi-IN"),
        polly_voice=os.environ.get("PUKAAR_POLLY_VOICE", "Kajal"),
        approval_timeout_seconds=int(os.environ.get("PUKAAR_APPROVAL_TIMEOUT_SECONDS", "600")),
        ack_wait_seconds=int(os.environ.get("PUKAAR_ACK_WAIT_SECONDS", "300")),
        replay_enabled=_bool("PUKAAR_REPLAY_ENABLED", True),
        data_dir=Path(os.environ.get("PUKAAR_DATA_DIR", str(_repo_data_dir()))),
        web_url=web_url,
        api_url=os.environ.get("PUKAAR_API_URL", "http://localhost:8000").rstrip("/"),
        ssm_prefix=os.environ.get("PUKAAR_SSM_PREFIX", "/pukaar"),
        hydromet_enabled=_bool("PUKAAR_HYDROMET_ENABLED", True),
        hydromet_timeout_seconds=float(os.environ.get("PUKAAR_HYDROMET_TIMEOUT_SECONDS", "12")),
        alerts_per_village_per_day=int(os.environ.get("PUKAAR_ALERTS_PER_VILLAGE_PER_DAY", "6")),
        # Soil-moisture modifier on the rain bands (services/soil.py). Default from the back-test in
        # docs/SCORING.md ("Soil moisture modifier").
        soil_modifier_enabled=_bool("PUKAAR_SOIL_MODIFIER", False),
        cors_origins=tuple(o.strip() for o in cors.split(",") if o.strip()),
        cognito_user_pool_id=os.environ.get("PUKAAR_COGNITO_USER_POOL_ID", ""),
        cognito_client_id=os.environ.get("PUKAAR_COGNITO_CLIENT_ID", ""),
        cap_sender=os.environ.get("PUKAAR_CAP_SENDER", "").strip()
        or f"pukaar-{os.environ.get('PUKAAR_STAGE', 'dev')}@{urlsplit(web_url).hostname or 'localhost'}",
        guardrail_id=os.environ.get("PUKAAR_GUARDRAIL_ID", ""),
        guardrail_version=os.environ.get("PUKAAR_GUARDRAIL_VERSION", ""),
        guardrail_timeout_seconds=float(os.environ.get("PUKAAR_GUARDRAIL_TIMEOUT_SECONDS", "8")),
        ses_from=os.environ.get("PUKAAR_SES_FROM", "").strip(),
        events_http_domain=os.environ.get("PUKAAR_EVENTS_HTTP_DOMAIN", "").strip().removeprefix("https://").rstrip("/"),
        stale_max_sweeps=int(os.environ.get("PUKAAR_STALE_MAX_SWEEPS", "4")),
        stale_alarm_minutes=int(os.environ.get("PUKAAR_STALE_ALARM_MINUTES", "45")),
        reask_cooldown_critical_minutes=max(0, min(5, int(os.environ.get("PUKAAR_REASK_COOLDOWN_CRITICAL_MINUTES",
                                                                       "5")))),
        reask_cooldown_warning_minutes=max(0, int(os.environ.get("PUKAAR_REASK_COOLDOWN_WARNING_MINUTES", "30"))),
        reask_cooldown_watch_minutes=max(0, int(os.environ.get("PUKAAR_REASK_COOLDOWN_WATCH_MINUTES", "60"))),
        voice_provider=_voice_provider(os.environ.get("PUKAAR_VOICE_PROVIDER", "off")),
        voice_max_attempts=max(1, min(5, int(os.environ.get("PUKAAR_VOICE_MAX_ATTEMPTS", "3")))),
        voice_ring_timeout_seconds=int(os.environ.get("PUKAAR_VOICE_RING_TIMEOUT_SECONDS", "40")),
        exotel_api_host=os.environ.get("PUKAAR_EXOTEL_API_HOST", "api.exotel.com").strip() or "api.exotel.com",
        critical_auto_send=_bool("PUKAAR_CRITICAL_AUTO_SEND", False),
        river_ensemble_enabled=_bool("PUKAAR_RIVER_ENSEMBLE", True),
        river_ensemble_p_min=min(1.0, max(0.02, float(os.environ.get("PUKAAR_RIVER_ENSEMBLE_P_MIN", "0.3")))),
        official_data_enabled=_bool("PUKAAR_OFFICIAL_DATA", True),
        official_raises_level=_bool("PUKAAR_OFFICIAL_RAISES_LEVEL", False),
        official_timeout_seconds=float(os.environ.get("PUKAAR_OFFICIAL_TIMEOUT_SECONDS", "5")),
        flood_hub_enabled=_bool("PUKAAR_FLOOD_HUB", False),
        bipad_enabled=_bool("PUKAAR_BIPAD", False),
        report_window_minutes=max(1, int(os.environ.get("PUKAAR_REPORT_WINDOW_MINUTES", "10"))),
        report_limit_per_source=max(1, int(os.environ.get("PUKAAR_REPORT_LIMIT_PER_SOURCE", "5"))),
        report_limit_per_village=max(1, int(os.environ.get("PUKAAR_REPORT_LIMIT_PER_VILLAGE", "30"))),
        rain_intensity_enabled=_bool("PUKAAR_RAIN_INTENSITY", True),
        rain_models=_rain_models(os.environ.get("PUKAAR_RAIN_MODELS", ",".join(DEFAULT_RAIN_MODELS))),
        rain_models_combine="mean" if os.environ.get("PUKAAR_RAIN_MODELS_COMBINE", "max").strip().lower() == "mean"
        else "max",
        cap_sender_name=os.environ.get("PUKAAR_CAP_SENDER_NAME", "").strip(),
        cap_sender_name_hi=os.environ.get("PUKAAR_CAP_SENDER_NAME_HI", "").strip(),
        report_retention_days=max(0, int(os.environ.get("PUKAAR_REPORT_RETENTION_DAYS", "0") or "0")),
        reading_retention_days=max(1, int(os.environ.get("PUKAAR_READING_RETENTION_DAYS", "30") or "30")),
        edge_required=_bool("PUKAAR_EDGE_REQUIRED", False),
        approval_timeout_critical_seconds=max(
            2, int(os.environ.get("PUKAAR_CRITICAL_APPROVAL_TIMEOUT_SECONDS", "300"))),
        officer_wake_seconds=max(0, int(os.environ.get("PUKAAR_OFFICER_WAKE_SECONDS", "180"))),
        delivery_batch_size=max(1, int(os.environ.get("PUKAAR_DELIVERY_BATCH_SIZE", "250"))),
        delivery_concurrency=max(1, min(40, int(os.environ.get("PUKAAR_DELIVERY_CONCURRENCY", "4")))),
        delivery_threads=max(1, min(64, int(os.environ.get("PUKAAR_DELIVERY_THREADS", "8")))),
        delivery_budget_seconds=max(1.0, float(os.environ.get("PUKAAR_DELIVERY_BUDGET_SECONDS", "200"))),
        delivery_max_passes=max(1, min(10, int(os.environ.get("PUKAAR_DELIVERY_MAX_PASSES", "4")))),
        telegram_rate_per_second=max(0.1, float(os.environ.get("PUKAAR_TELEGRAM_RATE_PER_SECOND", "25"))),
        telegram_chat_interval_seconds=max(0.0, float(os.environ.get("PUKAAR_TELEGRAM_CHAT_INTERVAL_SECONDS", "1"))),
        voice_calls_per_second=max(0.1, float(os.environ.get("PUKAAR_VOICE_CALLS_PER_SECOND", "2"))),
        sweep_concurrency=max(1, min(64, int(os.environ.get("PUKAAR_SWEEP_CONCURRENCY", "16")))),
        device_shadow="iot" if os.environ.get("PUKAAR_DEVICE_SHADOW", "iot" if mode == "aws" else "local")
        .strip().lower() == "iot" else "local",
        siren_check_seconds=max(30, int(os.environ.get("PUKAAR_SIREN_CHECK_SECONDS", "180"))),
        siren_commands_per_village_per_hour=max(1, int(os.environ.get("PUKAAR_SIREN_COMMANDS_PER_HOUR", "6"))),
        rain_obs_enabled=_bool("PUKAAR_RAIN_OBS", True),
        counters_max_age_seconds=max(0, int(os.environ.get("PUKAAR_COUNTERS_MAX_AGE_SECONDS",
                                                           "1200" if mode == "aws" else "0"))),
        telegram_shared_limit=_bool("PUKAAR_TELEGRAM_SHARED_LIMIT", mode == "aws"),
        unlinked_retention_days=max(0, int(os.environ.get("PUKAAR_UNLINKED_RETENTION_DAYS", "30") or "30")),
    )


# Open-Meteo forecast models the burst rule may read. Three models with the precipitation and two
# soil layers are 9 variables: still one call on the free tier (more than 10 counts as more).
RAIN_MODELS_ALLOWED = ("best_match", "icon_seamless", "gfs_seamless")
DEFAULT_RAIN_MODELS = RAIN_MODELS_ALLOWED


def _rain_models(raw: str) -> tuple[str, ...]:
    """best_match first, then any other allowed model named; unknown names are dropped."""
    names = [m.strip().lower() for m in raw.split(",") if m.strip()]
    return ("best_match", *dict.fromkeys(m for m in names if m in RAIN_MODELS_ALLOWED and m != "best_match"))


def _voice_provider(raw: str) -> str:
    """Anything but exotel or plivo is off: a typo never turns calling on."""
    value = raw.strip().lower()
    return value if value in {"exotel", "plivo"} else "off"
