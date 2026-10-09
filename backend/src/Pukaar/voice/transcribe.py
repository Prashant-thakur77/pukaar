"""Amazon Transcribe batch job on a stored voice report (hi-IN).

The browser uploads its own recording (webm/ogg/mp4/wav); Transcribe batch
accepts these directly, so no transcoding is needed. The audio stays in S3
next to the transcript, so a failed transcription never loses a report.
"""

from __future__ import annotations

import json
import time
import urllib.request

import boto3

from Pukaar.core.config import get_settings
from Pukaar.core.log import get_logger, log
from Pukaar.services import storage

_LOG = get_logger("transcribe")
FORMATS = {"webm": "webm", "ogg": "ogg", "mp4": "mp4", "m4a": "mp4", "wav": "wav", "mp3": "mp3", "flac": "flac", "amr": "amr"}


def media_format(key: str) -> str:
    return FORMATS.get(key.rsplit(".", 1)[-1].lower(), "webm")


def transcribe_key(audio_key: str, job_name: str, *, timeout_seconds: int = 240, client=None) -> str | None:
    s = get_settings()
    if s.is_local and client is None:
        return None
    client = client or boto3.client("transcribe", region_name=s.aws_region)
    try:
        client.start_transcription_job(
            TranscriptionJobName=job_name,
            LanguageCode=s.transcribe_language,
            MediaFormat=media_format(audio_key),
            Media={"MediaFileUri": storage.s3_uri(audio_key)},
        )
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            job = client.get_transcription_job(TranscriptionJobName=job_name)["TranscriptionJob"]
            status = job["TranscriptionJobStatus"]
            if status == "COMPLETED":
                with urllib.request.urlopen(job["Transcript"]["TranscriptFileUri"], timeout=15) as resp:  # noqa: S310 (AWS presigned URL)
                    data = json.loads(resp.read())
                text = " ".join(t["transcript"] for t in data["results"]["transcripts"]).strip()
                log(_LOG, "transcribed", job=job_name, chars=len(text))
                return text
            if status == "FAILED":
                log(_LOG, "transcription failed", 30, job=job_name, reason=job.get("FailureReason"))
                return None
            time.sleep(2)
        log(_LOG, "transcription timed out", 30, job=job_name)
    except Exception as exc:
        log(_LOG, "transcribe error", 30, job=job_name, error=str(exc)[:200])
    return None
