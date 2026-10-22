"""Amazon Polly: Hindi speech for an alert, stored in S3 under the alert id.

Speech is only ever made from server-stored alert text (never client text).
Generative engine first, with a logged fallback to neural.

Phone calls (docs/VOICE.md) need 8 kHz mono audio: Exotel plays only 8 kHz MP3 or WAV, so the
call copy is made apart from the Telegram copy (synthesize_call_audio), and the "press 1, 2 or 3"
menu is made once and kept (menu_audio_key).
"""

from __future__ import annotations

import boto3

from Pukaar.core.config import get_settings
from Pukaar.core.log import get_logger, log
from Pukaar.services import storage

MAX_CHARS = 1500
_LOG = get_logger("polly")


MENU_KEY = "audio/calls/menu-hi-v1.mp3"


def _synthesize(key: str, text_hi: str, client=None, sample_rate: str | None = None, **ctx) -> str | None:
    s = get_settings()
    if s.is_local and client is None:
        return None  # no Polly offline; the UI shows the text instead
    client = client or boto3.client("polly", region_name=s.aws_region)
    extra = {"SampleRate": sample_rate} if sample_rate else {}
    for engine in ("generative", "neural"):
        try:
            resp = client.synthesize_speech(Text=text_hi[:MAX_CHARS], VoiceId=s.polly_voice, LanguageCode="hi-IN",
                                            OutputFormat="mp3", Engine=engine, **extra)
            storage.put_bytes(key, resp["AudioStream"].read(), "audio/mpeg")
            log(_LOG, "audio stored", key=key, engine=engine, **ctx)
            return key
        except Exception as exc:
            log(_LOG, "polly failed", 30, engine=engine, error=str(exc)[:200], **ctx)
    return None


def synthesize_alert(alert_id: str, text_hi: str, client=None) -> str | None:
    """Returns the S3 key of the MP3, or None when Polly is unavailable."""
    return _synthesize(f"audio/alerts/{alert_id}.mp3", text_hi, client, alert_id=alert_id)


def synthesize_call_audio(alert_id: str, text_hi: str, client=None) -> str | None:
    """The 8 kHz copy a phone call plays. None when Polly is unavailable (the call then speaks the text)."""
    return _synthesize(f"audio/calls/{alert_id}.mp3", text_hi, client, sample_rate="8000", alert_id=alert_id)


def menu_audio_key(client=None) -> str | None:
    """The 8 kHz "press 1, 2 or 3" menu, made once."""
    from Pukaar.templates import hi

    try:
        storage.get_bytes(MENU_KEY)
        return MENU_KEY
    except Exception:
        return _synthesize(MENU_KEY, hi.VOICE_MENU_HI, client, sample_rate="8000", alert_id="menu")
