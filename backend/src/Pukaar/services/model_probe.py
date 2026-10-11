"""A cheap, cached check of whether this account may call the Bedrock model.

The live stack drafts with the fixed Hindi template while Bedrock model access is
pending (an AWS support case). The public /agents page must say so honestly, and
must say "Live" on its own the day access lands, without calling a model itself.

So the 15-minute sweep runs this at most once every 6 hours: one Converse call
with maxTokens 1 (a fraction of a cent), on the drafting model. The answer is
cached in DynamoDB (pk MODELPROBE, sk META):

  access              "live" | "pending" (the last definite answer; kept through errors)
  access_checked_at   when that answer was seen
  checked_at          when the last probe ran (any outcome; the 6-hour clock)
  state               "live" | "pending" | "error" (the last probe's own outcome)
  detail              the error code and a short message, never a secret

Access errors ("AccessDeniedException", a ValidationException "Operation not
allowed", or a ResourceNotFoundException about model access / use case details)
mean pending. Anything else (throttling, a timeout) is "error" and leaves the
last definite answer alone. Never raises into the sweep.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.log import get_logger, log
from Pukaar.store.repo import Repo

_LOG = get_logger("model_probe")
PROBE_EVERY = timedelta(hours=6)
PENDING_EVIDENCE = ("Bedrock model access for this account is pending an AWS support case; "
                    "drafts use the fixed Hindi template")
PENDING_EVIDENCE_HI = "इस खाते के लिए Bedrock मॉडल की अनुमति AWS सपोर्ट केस में बाकी है; ड्राफ़्ट तय हिंदी ढाँचे से बनते हैं"
_ACCESS_HINTS = ("operation not allowed", "access denied", "not authorized", "don't have access", "do not have access",
                 "model access", "use case details", "not subscribed", "is not enabled")


def classify(exc: BaseException) -> tuple[str, str]:
    """(state, detail) for a failed probe: "pending" for an access refusal, else "error"."""
    code = ""
    msg = str(exc)
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        err = response.get("Error", {}) or {}
        code = str(err.get("Code", ""))
        msg = str(err.get("Message", msg))
    lowered = msg.lower()
    detail = f"{code or type(exc).__name__}: {msg[:160]}"
    if code in ("AccessDeniedException", "AccessDenied"):
        return "pending", detail
    if code in ("ValidationException", "ResourceNotFoundException") and any(h in lowered for h in _ACCESS_HINTS):
        return "pending", detail
    if not code and any(h in lowered for h in _ACCESS_HINTS):
        return "pending", detail
    return "error", detail


def _converse_once(model_id: str, region: str) -> None:
    import boto3
    from botocore.config import Config

    client = boto3.client("bedrock-runtime", region_name=region,
                          config=Config(connect_timeout=5, read_timeout=15, retries={"max_attempts": 1}))
    client.converse(modelId=model_id, messages=[{"role": "user", "content": [{"text": "OK"}]}],
                    inferenceConfig={"maxTokens": 1, "temperature": 0})


def maybe_run(repo: Repo, *, call: Callable[[str, str], None] | None = None, force: bool = False) -> dict[str, Any] | None:
    """Probe model access if model calls are on and no probe ran in the last 6 hours.

    Returns the stored record when a probe ran, None when it was skipped. Never raises.
    """
    try:
        s = get_settings()
        if not s.llm_enabled:
            return None
        now = clock.now()
        now_iso = clock.iso(now)
        not_before = clock.iso(now - PROBE_EVERY) if not force else now_iso
        if not force and not repo.claim_model_probe(now_iso, not_before):
            return None
        if force:
            repo.put_model_probe({"checked_at": now_iso})
        try:
            (call or _converse_once)(s.bedrock_model_id, s.aws_region)
            state, detail = "live", "model answered a 1-token Converse call"
        except Exception as exc:  # the answer we came for
            state, detail = classify(exc)
        fields: dict[str, Any] = {"state": state, "detail": detail, "model": s.bedrock_model_id,
                                  "checked_at": now_iso}
        if state in ("live", "pending"):
            fields |= {"access": state, "access_checked_at": now_iso}
        repo.put_model_probe(fields)
        log(_LOG, "model access probe", state=state, model=s.bedrock_model_id)
        return repo.get_model_probe()
    except Exception as exc:  # the sweep must never fail because of this
        log(_LOG, "model access probe failed", 30, error=str(exc))
        return None
