"""Live push to the web app over AWS AppSync Events.

The backend publishes small JSON events with a SigV4-signed POST to
https://<http domain>/event; browsers subscribe over a WebSocket and refetch
the page data they show. Polling stays on as the fallback, so a lost event
only means the page catches up at its next poll.

Channels (infra/template.yaml, namespaces "public" and "officer"):

  /public/levels      a village's level changed         anyone (API key)
  /public/alerts      an alert's status changed         anyone (API key)
  /public/deliveries  delivered / acknowledged counts   anyone (API key)
  /public/rollcall    roll-call counts for a village    anyone (API key)
  /officer/alerts     approvals and roll-call "need help"  signed-in users (Cognito)

Payloads carry ids, levels, statuses, times and counts only: never alert
text, names, chat ids or phone numbers. Each builder below picks its fields
by name, so a new model field can never leak into an event by accident.

publish() never raises: a failure is logged and counted (EventPublishFailed)
and the caller carries on. With no PUKAAR_EVENTS_HTTP_DOMAIN (local mode, tests)
nothing is sent.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Protocol

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.log import get_logger, log, metric
from Pukaar.store.models import Alert, RollCall

_LOG = get_logger("events")

PUBLIC_LEVELS = "/public/levels"
PUBLIC_ALERTS = "/public/alerts"
PUBLIC_DELIVERIES = "/public/deliveries"
PUBLIC_ROLLCALL = "/public/rollcall"
OFFICER_ALERTS = "/officer/alerts"

TIMEOUT_SECONDS = 2.0  # a slow push must never hold up a sweep or an approval


class HttpClient(Protocol):
    def post(self, url: str, *, content: bytes, headers: dict[str, str], timeout: float) -> Any: ...


_client: HttpClient | None = None
_lock = threading.Lock()


def set_client(client: HttpClient | None) -> None:
    """Tests inject a fake; None goes back to the real httpx client."""
    global _client
    _client = client


def _http() -> HttpClient:
    global _client
    with _lock:
        if _client is None:
            import httpx

            _client = httpx.Client()
        return _client


def configured() -> bool:
    return bool(get_settings().events_http_domain)


def _signed_headers(url: str, body: bytes, region: str) -> dict[str, str]:
    """SigV4 for service "appsync" with the function's own role (no API key on the server)."""
    import boto3
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    creds = boto3.Session().get_credentials()
    if creds is None:
        raise RuntimeError("no AWS credentials to sign the publish")
    req = AWSRequest(method="POST", url=url, data=body, headers={"content-type": "application/json"})
    SigV4Auth(creds.get_frozen_credentials(), "appsync", region).add_auth(req)
    return dict(req.headers.items())


def publish(channel: str, event: dict[str, Any]) -> bool:
    """Publish one event. True when AppSync accepted it; never raises."""
    s = get_settings()
    if not s.events_http_domain:
        return False
    namespace = channel.strip("/").split("/", 1)[0]
    try:
        url = f"https://{s.events_http_domain}/event"
        body = json.dumps({"channel": channel, "events": [json.dumps(event, separators=(",", ":"))]},
                          separators=(",", ":")).encode()
        resp = _http().post(url, content=body, headers=_signed_headers(url, body, s.aws_region),
                            timeout=TIMEOUT_SECONDS)
        if resp.status_code >= 300:
            raise RuntimeError(f"HTTP {resp.status_code}: {str(getattr(resp, 'text', ''))[:200]}")
        try:
            failed = (resp.json() or {}).get("failed") or []
        except Exception:
            failed = []
        if failed:
            raise RuntimeError(f"rejected: {str(failed)[:200]}")
        return True
    except Exception as exc:
        log(_LOG, "event publish failed", 30, channel=channel, error=f"{type(exc).__name__}: {str(exc)[:200]}")
        metric("EventPublishFailed", 1, Namespace=namespace)
        return False


# -- payload builders: fields picked by name, no personal data -------------------------
def level_event(village_id: str, level: str, previous: str, *, replay: bool = False, at: str | None = None) -> dict:
    return {"type": "level", "village_id": village_id, "level": level, "previous": previous,
            "replay": bool(replay), "at": at or clock.iso(clock.now())}


def alert_event(alert: Alert) -> dict:
    return {"type": "alert", "alert_id": alert.id, "village_id": alert.village_id, "level": alert.level,
            "status": alert.status, "replay": bool(alert.replay), "at": clock.iso(clock.now())}


def delivery_event(alert: Alert) -> dict:
    return {"type": "delivery", "alert_id": alert.id, "village_id": alert.village_id,
            "recipients_count": int(alert.recipients_count), "delivered_count": int(alert.delivered_count),
            "acknowledged_count": int(alert.acknowledged_count), "at": clock.iso(clock.now())}


def rollcall_event(rc: RollCall) -> dict:
    return {"type": "rollcall", "rollcall_id": rc.id, "village_id": rc.village_id, "exercise": bool(rc.exercise),
            "asked": int(rc.asked), "safe": int(rc.safe), "need_help": int(rc.need_help),
            "not_answered": max(int(rc.asked) - int(rc.safe) - int(rc.need_help), 0), "at": clock.iso(clock.now())}


# Alert statuses that change what an officer must do in the console.
_OFFICER_KINDS = {"pending": "approval_pending", "approved": "approved", "declined": "declined",
                  "expired": "expired", "auto_sent_unapproved": "auto_sent", "failsafe": "failsafe"}


def officer_alert_event(alert: Alert, kind: str) -> dict:
    return {"type": "approval", "kind": kind, "alert_id": alert.id, "village_id": alert.village_id,
            "level": alert.level, "status": alert.status, "replay": bool(alert.replay), "at": clock.iso(clock.now())}


# -- what the rest of the code calls -----------------------------------------------------
def level_changed(village_id: str, level: str, previous: str, *, replay: bool = False) -> None:
    if level != previous:
        publish(PUBLIC_LEVELS, level_event(village_id, level, previous, replay=replay))


def alert_changed(alert: Alert | None, *, kind: str | None = None) -> None:
    """Public status event, plus an officer event when the change needs an officer's eye."""
    if alert is None or not configured():
        return
    publish(PUBLIC_ALERTS, alert_event(alert))
    kind = kind or _OFFICER_KINDS.get(alert.status)
    if kind:
        publish(OFFICER_ALERTS, officer_alert_event(alert, kind))


def counts_changed(alert: Alert | None) -> None:
    if alert is not None and configured():
        publish(PUBLIC_DELIVERIES, delivery_event(alert))


def rollcall_changed(rc: RollCall | None, *, need_help: bool = False) -> None:
    if rc is None or not configured():
        return
    publish(PUBLIC_ROLLCALL, rollcall_event(rc))
    if need_help:
        publish(OFFICER_ALERTS, {"type": "rollcall", "kind": "need_help", "rollcall_id": rc.id,
                                 "village_id": rc.village_id, "need_help": int(rc.need_help),
                                 "exercise": bool(rc.exercise), "at": clock.iso(clock.now())})
