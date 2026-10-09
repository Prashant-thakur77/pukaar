"""Amazon Polly: Hindi speech for an alert, stored in S3 under the alert id.

Speech is only ever made from server-stored alert text (never client text).
Generative engine first, with a logged fallback to neural.
"""

from __future__ import annotations

import boto3

from Pukaar.core.config import get_settings
from Pukaar.core.log import get_logger, log
from Pukaar.services import storage

MAX_CHARS = 1500
_LOG = get_logger("polly")


def synthesize_alert(alert_id: str, text_hi: str, client=None) -> str | None:
    """Returns the S3 key of the MP3, or None when Polly is unavailable."""
    s = get_settings()
    if s.is_local and client is None:
        return None  # no Polly offline; the UI shows the text instead
    client = client or boto3.client("polly", region_name=s.aws_region)
    for engine in ("generative", "neural"):
        try:
            resp = client.synthesize_speech(Text=text_hi[:MAX_CHARS], VoiceId=s.polly_voice, LanguageCode="hi-IN",
                                            OutputFormat="mp3", Engine=engine)
            key = f"audio/alerts/{alert_id}.mp3"
            storage.put_bytes(key, resp["AudioStream"].read(), "audio/mpeg")
            log(_LOG, "alert audio stored", alert_id=alert_id, engine=engine)
            return key
        except Exception as exc:
            log(_LOG, "polly failed", 30, alert_id=alert_id, engine=engine, error=str(exc)[:200])
    return None
