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
    # A declined or expired alert is asked again after this long if the level still holds.
    reask_cooldown_minutes: int = 30
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
    # the alert expires unsent and the sweep asks again after the cooldown.
    critical_auto_send: bool = True
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
        reask_cooldown_minutes=int(os.environ.get("PUKAAR_REASK_COOLDOWN_MINUTES", "30")),
        voice_provider=_voice_provider(os.environ.get("PUKAAR_VOICE_PROVIDER", "off")),
        voice_max_attempts=max(1, min(5, int(os.environ.get("PUKAAR_VOICE_MAX_ATTEMPTS", "3")))),
        voice_ring_timeout_seconds=int(os.environ.get("PUKAAR_VOICE_RING_TIMEOUT_SECONDS", "40")),
        exotel_api_host=os.environ.get("PUKAAR_EXOTEL_API_HOST", "api.exotel.com").strip() or "api.exotel.com",
        critical_auto_send=_bool("PUKAAR_CRITICAL_AUTO_SEND", True),
        river_ensemble_enabled=_bool("PUKAAR_RIVER_ENSEMBLE", True),
        river_ensemble_p_min=min(1.0, max(0.02, float(os.environ.get("PUKAAR_RIVER_ENSEMBLE_P_MIN", "0.3")))),
        official_data_enabled=_bool("PUKAAR_OFFICIAL_DATA", True),
        official_raises_level=_bool("PUKAAR_OFFICIAL_RAISES_LEVEL", False),
        official_timeout_seconds=float(os.environ.get("PUKAAR_OFFICIAL_TIMEOUT_SECONDS", "5")),
        flood_hub_enabled=_bool("PUKAAR_FLOOD_HUB", False),
        bipad_enabled=_bool("PUKAAR_BIPAD", False),
    )


def _voice_provider(raw: str) -> str:
    """Anything but exotel or plivo is off: a typo never turns calling on."""
    value = raw.strip().lower()
    return value if value in {"exotel", "plivo"} else "off"
