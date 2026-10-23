"""The live jury demo (docs/DEMO_LIVE.md): jurors join from their own phones, the presenter approves one
labelled practice alert as the duty officer, and each juror's Telegram gets the spoken Hindi alert with the
"मिल गया" button while the presenter screen (/console/demo) counts joined, delivered and confirmed.

Safety first, by construction rather than by filters:

- The demo village (id "demo", "डेमो गाँव / Demo village", district "Demo") is a Village with demo=True. It is
  never put in the village registry, so nothing that lists villages sees it: the public pages, the sweep (rules,
  forecasts, sirens), the CAP feed and its all-clears, the counters, the pilot metrics, the roster, the IVR
  keypad. Repo.get_village hides it unless asked (include_demo), so a public page, a report, the enrolment form or
  a SACHET request that names it finds nothing.
- A demo alert carries decision_trace demo (and drill: every drill label applies) and is written to DEMOLOG,
  never ALERTLOG, so no list of alerts (and no metric, feed or after-alert job) ever reads it.
- Delivery takes the recipients of the alert's own village, and dispatch keeps only demo people for a demo alert
  and only non-demo people for any other (dispatch._same_world); Cedar "demo-stays-in-demo" refuses a demo alert
  outside the demo village, or any other alert inside it, and "demo-never-without-an-officer" refuses its
  auto-send and failsafe.
- Joining: Telegram "/start demo-<code>", a 4-digit code that rotates per session and expires after 30 minutes,
  shown only on the presenter screen. The notice (Hindi and English) comes first; nothing about the person is
  stored before "I agree". At most 50 people per session, one demo alert per 2 minutes.
- Erasure: the sweep deletes demo people and demo alerts (with their delivery rows) 24 hours after they were made
  (erase_due), and "reset demo" deletes everything at once. Audit rows say "demo" and hold no personal data.
"""

from __future__ import annotations

import hmac
import secrets
from datetime import datetime, timedelta
from statistics import median
from typing import Any

from boto3.dynamodb.conditions import Attr

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.ids import new_id
from Pukaar.core.log import get_logger, log, metric
from Pukaar.store.models import OPEN_ALERT_STATUSES, Alert, AuditRow, Recipient, Village
from Pukaar.store.repo import ConflictError, Repo
from Pukaar.templates import script

_LOG = get_logger("demo")

VILLAGE_ID = "demo"
VILLAGE_NAME, VILLAGE_NAME_HI = "Demo village", "डेमो गाँव"
DISTRICT, DISTRICT_HI = "Demo", "डेमो"
LEVEL = "warning"
MAX_PEOPLE = 50  # per session
ALERT_EVERY_SECONDS = 120  # one demo alert per 2 minutes
CODE_TTL_SECONDS = 30 * 60  # the join code expires after 30 minutes
KEEP_HOURS = 24  # demo people and demo alerts are erased this long after they were made
NOTICE_VERSION = "demo-notice-v1"
VIA = "demo"  # Recipient.enrolled_via of every demo person, and only of them

LABEL_HI = "अभ्यास / DEMO — यह असली चेतावनी नहीं है (this is not a real warning)।"
LABEL_EN = "अभ्यास / DEMO — this is not a real warning."
# The fixed script's own evidence: what a Warning from heavy rain in the next 6 hours would say.
_TRACE = {"rules_fired": ["rain_24h"], "nowcast": {"hours": 6}}

NOTICE = (
    "पुकार · डेमो: यह टाटा इमेजिनेशन चैलेंज के निर्णायकों के लिए एक डेमो है। आपको “DEMO” लिखा एक अभ्यास संदेश "
    "मिलेगा, असली चेतावनी नहीं। आपका टेलीग्राम नाम और चैट आईडी 24 घंटे में मिटा दिए जाएँगे। "
    "“सहमत हूँ” दबाने से पहले कुछ नहीं रखा जाता। कभी भी छोड़ने के लिए /stop लिखें।\n\n"
    "Pukaar · demo: This is a demo for the Tata Imagination Challenge jury; you will get one practice alert marked "
    "DEMO; your Telegram name and chat id are deleted within 24 hours. Nothing is stored before you press "
    "“I agree”. Send /stop to leave at any time."
)
JOINED = ("पुकार · डेमो: आप जुड़ गए। प्रस्तुतकर्ता के मंज़ूर करते ही अभ्यास संदेश आएगा; सुनें और “मिल गया” दबाएँ।\n"
          "Pukaar · demo: you are in. The practice alert comes as soon as the presenter approves it: listen, then "
          "press “मिल गया”.")
EXPIRED = ("पुकार · डेमो: यह कोड पुराना है या बदल गया। स्क्रीन पर दिया नया QR स्कैन करें।\n"
           "Pukaar · demo: this code has expired or changed. Scan the new QR code on the screen.")
FULL = (f"पुकार · डेमो: यह डेमो भर गया ({MAX_PEOPLE} लोग)।\n"
        f"Pukaar · demo: this demo is full ({MAX_PEOPLE} people).")
ALREADY = "पुकार · डेमो: आप पहले से जुड़े हैं। · Pukaar · demo: you are already in."
OFF = "पुकार · डेमो: डेमो अभी बंद है। · Pukaar · demo: the demo is not running."


class DemoError(Exception):
    """A refusal the caller shows as it is: code, HTTP status, English and Hindi."""

    def __init__(self, code: str, status: int, message_en: str, message_hi: str, **extra: Any) -> None:
        super().__init__(message_en)
        self.code, self.status, self.message_en, self.message_hi, self.extra = code, status, message_en, message_hi, extra

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message_en": self.message_en, "message_hi": self.message_hi, **self.extra}


def enabled() -> bool:
    return get_settings().live_demo_enabled


def is_demo(alert: Alert | None) -> bool:
    return bool(alert is not None and (alert.decision_trace or {}).get("demo"))


def is_demo_person(r: Recipient) -> bool:
    return r.enrolled_via == VIA


def village() -> Village:
    """The demo village. Its place is a point near Shimla only so every map and bound check has one; it is not a
    real village and never appears on any map."""
    return Village(id=VILLAGE_ID, name=VILLAGE_NAME, name_hi=VILLAGE_NAME_HI, district=DISTRICT, district_hi=DISTRICT_HI,
                   lat=31.10, lon=77.17, coords_verified=False, coords_source="demo: not a real place", demo=True)


def ensure_village(repo: Repo) -> Village:
    v = repo.get_village(VILLAGE_ID, include_demo=True)
    if v is not None and v.demo:
        return v
    if v is not None:  # a real village with this id would never be overwritten
        raise DemoError("id_taken", 409, "A real village already uses the id 'demo'.", "'demo' आईडी एक असली गाँव की है।")
    v = village()
    repo.put_village(v)
    return v


def script_text() -> tuple[str, str]:
    """The fixed demo script, five-element style (templates/script.py), naming the demo village, under the label."""
    body_hi, body_en = script.compose(LEVEL, VILLAGE_NAME_HI, VILLAGE_NAME, district_hi=DISTRICT_HI, district_en=DISTRICT,
                                      trace=_TRACE)
    return f"{LABEL_HI} {body_hi}", f"{LABEL_EN} {body_en}"


def join_link(code: str) -> str:
    return f"https://t.me/{get_settings().telegram_bot_username}?start=demo-{code}"


def presenter_url() -> str:
    return f"{get_settings().web_url}/console/demo"


def _audit(repo: Repo, now: datetime, actor: str, role: str, action: str, reason: str, session_id: str = "") -> None:
    """One audit row: "demo" and counts only, never a name or a chat id."""
    repo.append_audit(AuditRow(at=clock.iso(now), id=new_id("aud"), actor=actor, role=role, action=action,
                               resource=f"demo:{session_id or 'none'}", decision="allow", reason=reason[:300]))


def _new_code(old: str | None = None) -> str:
    while True:
        code = f"{secrets.randbelow(10_000):04d}"
        if code != old:
            return code


def _expired(session: dict[str, Any], now: datetime) -> bool:
    try:
        return now >= clock.parse(str(session.get("code_expires_at")))
    except (TypeError, ValueError):
        return True


# -- the session --------------------------------------------------------------------------------------
def open_session(repo: Repo, by: str, role: str = "officer", now: datetime | None = None) -> dict[str, Any]:
    """Start a session, or give the running one a new code (the old one stops working at once). Its people stay."""
    if not enabled():
        raise DemoError("disabled", 403, "The live demo is off on this stack (PUKAAR_LIVE_DEMO).",
                        "इस स्टैक पर लाइव डेमो बंद है।")
    now = now or clock.now()
    ensure_village(repo)
    s = repo.get_demo_session()
    expires = clock.iso(now + timedelta(seconds=CODE_TTL_SECONDS))
    if s is None:
        s = {"session_id": new_id("demo"), "code": _new_code(), "code_expires_at": expires, "opened_by": by,
             "opened_at": clock.iso(now), "joined": 0}
        repo.put_demo_session(s)
        _audit(repo, now, by, role, "demo_open", "live demo session opened; join code shown on the presenter screen",
               s["session_id"])
    else:
        s = repo.update_demo_session({"code": _new_code(str(s.get("code"))), "code_expires_at": expires,
                                      "code_by": by})
        _audit(repo, now, by, role, "demo_code", "live demo join code rotated (the old one no longer works)",
               str(s.get("session_id")))
    return s


def _session_or_raise(repo: Repo) -> dict[str, Any]:
    s = repo.get_demo_session()
    if s is None:
        raise DemoError("no_session", 409, "Open the demo first: it makes the join code.", "पहले डेमो खोलें: उससे कोड बनता है।")
    return s


# -- joining (Telegram) ----------------------------------------------------------------------------------
def ask_consent(repo: Repo, chat_id: str, code: str, now: datetime | None = None) -> str:
    """"/start demo-<code>": the notice to show, after checking the code. Stores nothing about the person: only the
    short "waiting for consent" row that names the code (it expires with the code)."""
    now = now or clock.now()
    s = repo.get_demo_session() if enabled() else None
    if s is None:
        raise DemoError("off", 409, OFF, OFF)
    if not _code_ok(s, code, now):
        raise DemoError("expired", 409, EXPIRED, EXPIRED)
    if repo.get_recipient(VILLAGE_ID, chat_id) is not None:
        raise DemoError("already", 409, ALREADY, ALREADY)
    if int(s.get("joined") or 0) >= MAX_PEOPLE:
        raise DemoError("full", 409, FULL, FULL)
    repo.put_consent_wait(chat_id, f"{VILLAGE_ID}:{code}", ttl_seconds=CODE_TTL_SECONDS)
    return NOTICE


def _code_ok(s: dict[str, Any], code: str, now: datetime) -> bool:
    return bool(code) and hmac.compare_digest(str(s.get("code") or ""), str(code)) and not _expired(s, now)


def join(repo: Repo, chat_id: str, code: str, first_name: str, now: datetime | None = None) -> Recipient:
    """"I agree" under the notice: only now is the person stored, in the demo village only, with the consent record.
    The code must still be the current one; the 50-person cap is one conditional ADD on the session."""
    now = now or clock.now()
    if not repo.consume_consent_wait(chat_id, f"{VILLAGE_ID}:{code}"):
        existing = repo.get_recipient(VILLAGE_ID, chat_id)
        if existing is not None:
            return existing  # a double tap
        raise DemoError("expired", 409, EXPIRED, EXPIRED)
    s = repo.get_demo_session() if enabled() else None
    if s is None or not _code_ok(s, code, now):
        raise DemoError("expired", 409, EXPIRED, EXPIRED)
    existing = repo.get_recipient(VILLAGE_ID, chat_id)
    if existing is not None:
        return existing
    try:
        repo.update_demo_session({}, condition=Attr("session_id").eq(s["session_id"])
                                 & (Attr("joined").not_exists() | Attr("joined").lt(MAX_PEOPLE)), add={"joined": 1})
    except ConflictError:
        raise DemoError("full", 409, FULL, FULL) from None
    stamp = clock.iso(now)
    person = Recipient(id=chat_id, village_id=VILLAGE_ID, name=(first_name or "").strip()[:40] or "Juror",
                       channel="telegram", consent=f"telegram button, {NOTICE_VERSION}, {stamp}", enrolled_via=VIA,
                       enrolled_by=str(s["session_id"]), joined_at=stamp)
    repo.put_recipient(person)
    _audit(repo, now, "pukaar-system", "system", "demo_join", "one person joined the live demo after the notice "
           "(their name and chat id are erased within 24 hours)", str(s["session_id"]))
    metric("DemoJoined", 1)
    return person


# -- the alert ----------------------------------------------------------------------------------------
def start_alert(repo: Repo, workflow: Any, by: str, role: str = "officer", now: datetime | None = None) -> Alert:
    """The presenter's "start the demo alert": one labelled alert for the demo village through the normal approval
    workflow (the presenter is the officer asked, and approves with hold-to-approve)."""
    from Pukaar.services.decision_engine import start_workflow

    if not enabled():
        raise DemoError("disabled", 403, "The live demo is off on this stack (PUKAAR_LIVE_DEMO).",
                        "इस स्टैक पर लाइव डेमो बंद है।")
    now = now or clock.now()
    s = _session_or_raise(repo)
    v = ensure_village(repo)
    if v.open_alert_id:
        open_alert = repo.get_alert(v.open_alert_id)
        if open_alert is not None and open_alert.status in OPEN_ALERT_STATUSES:
            raise DemoError("open", 409, "The demo alert is still open: approve or decline it first.",
                            "डेमो संदेश अभी खुला है: पहले उसे मंज़ूर या अस्वीकार करें।", alert_id=open_alert.id)
    cutoff = clock.iso(now - timedelta(seconds=ALERT_EVERY_SECONDS))
    try:  # one demo alert per 2 minutes, for every presenter and Lambda at once
        repo.update_demo_session({"last_alert_at": clock.iso(now)},
                                 condition=Attr("last_alert_at").not_exists() | Attr("last_alert_at").lte(cutoff))
    except ConflictError:
        wait = ALERT_EVERY_SECONDS
        try:
            wait = max(1, ALERT_EVERY_SECONDS - int((now - clock.parse(str(s.get("last_alert_at")))).total_seconds()))
        except (TypeError, ValueError):
            pass
        raise DemoError("too_soon", 429, f"One demo alert per 2 minutes: try again in {wait} s.",
                        f"हर 2 मिनट में एक डेमो संदेश: {wait} सेकंड बाद फिर कोशिश करें।", retry_after=wait) from None
    people = [r for r in repo.list_recipients(VILLAGE_ID) if is_demo_person(r)]
    text_hi, text_en = script_text()
    stamp = clock.iso(now)
    alert = Alert(id=new_id("alr"), village_id=VILLAGE_ID, village_name=VILLAGE_NAME, village_name_hi=VILLAGE_NAME_HI,
                  level=LEVEL, status="drafting", created_at=stamp, updated_at=stamp, text_hi=text_hi, text_en=text_en,
                  district=DISTRICT, recipients_count=len(people),
                  decision_trace={"demo": True, "drill": True, "rules_fired": ["demo"], "demo_session": s["session_id"],
                                  "started_by": by})
    repo.put_alert(alert)
    repo.update_village(VILLAGE_ID, open_alert_id=alert.id, last_alert_id=alert.id)
    repo.update_demo_session({"alert_id": alert.id})
    repo.add_timeline(alert.id, "created", f"live jury demo, started by {by}: the fixed DEMO script to "
                                           f"{len(people)} demo phone(s) only")
    _audit(repo, now, by, role, "demo_alert", f"demo alert {alert.id} started for {len(people)} demo phone(s)",
           str(s["session_id"]))
    if not start_workflow(repo, workflow, alert):
        log(_LOG, "demo workflow did not start; the sweep retries it", 30, alert_id=alert.id)
    return repo.get_alert(alert.id) or alert


# -- the presenter screen -----------------------------------------------------------------------------------
def _seconds(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    return round((clock.parse(end) - clock.parse(start)).total_seconds(), 1)


def _latest_alert(repo: Repo, s: dict[str, Any] | None) -> Alert | None:
    aid = (s or {}).get("alert_id")
    if aid:
        a = repo.get_alert(str(aid))
        if a is not None:
            return a
    ids = repo.demo_alert_ids()
    return repo.get_alert(ids[-1][1]) if ids else None


def alert_view(repo: Repo, a: Alert) -> dict[str, Any]:
    """Counts and times only: no names, no chat ids."""
    rows = [d for d in repo.list_deliveries(a.id) if d.channel != "stub"]
    people: dict[str, list] = {}
    for d in rows:
        people.setdefault(d.recipient_id, []).append(d)
    sent = [d.sent_at for d in rows if d.sent_at]
    acks = sorted(d.acknowledged_at for d in rows if d.acknowledged_at)
    first_sent = min(sent) if sent else None
    approved_at = a.decided_at if a.approved else None
    from_send = [x for x in (_seconds(first_sent, t) for t in acks) if x is not None]
    from_approval = [x for x in (_seconds(approved_at, t) for t in acks) if x is not None]
    timeline = repo.list_timeline(a.id)
    asked = next((t.at for t in timeline if t.step == "asked_officer"), None)
    return {
        "id": a.id, "status": a.status, "level": a.level, "created_at": a.created_at, "decided_at": a.decided_at,
        "approved": a.approved, "text_hi": a.text_hi, "text_en": a.text_en, "has_audio": bool(a.audio_key),
        "targeted": len(people),
        "delivered": sum(1 for ds in people.values() if any(d.status in {"sent", "acknowledged"} or d.acknowledged_at
                                                            for d in ds)),
        "confirmed": len({d.recipient_id for d in rows if d.acknowledged_at}),
        "failed": sum(1 for ds in people.values() if all(d.status == "failed" for d in ds)),
        "times": {"created": a.created_at, "asked": asked, "approved": approved_at, "first_sent": first_sent,
                  "first_ack": acks[0] if acks else None},
        "seconds": {
            "approved_to_first_sent": _seconds(approved_at, first_sent),
            "first_sent_to_first_ack": from_send[0] if from_send else None,
            "first_sent_to_median_ack": round(median(from_send), 1) if from_send else None,
            "approved_to_first_ack": from_approval[0] if from_approval else None,
            "approved_to_median_ack": round(median(from_approval), 1) if from_approval else None,
        },
    }


def status(repo: Repo, *, show_code: bool, now: datetime | None = None) -> dict[str, Any]:
    """What the presenter screen shows. The code and its link only for someone who may run the demo (never the public
    demo accounts, whose password is published)."""
    now = now or clock.now()
    s = repo.get_demo_session()
    people = [r for r in repo.list_recipients(VILLAGE_ID) if is_demo_person(r)] if s is not None else []
    a = _latest_alert(repo, s) if s is not None else None
    next_at = None
    if s is not None and s.get("last_alert_at"):
        try:
            nxt = clock.parse(str(s["last_alert_at"])) + timedelta(seconds=ALERT_EVERY_SECONDS)
            next_at = clock.iso(nxt) if nxt > now else None
        except ValueError:
            next_at = None
    code_live = s is not None and not _expired(s, now)
    out: dict[str, Any] = {
        "enabled": enabled(), "open": s is not None, "village": {"id": VILLAGE_ID, "name": VILLAGE_NAME,
                                                                  "name_hi": VILLAGE_NAME_HI, "district": DISTRICT},
        "code": None, "join_url": None, "bot": get_settings().telegram_bot_username,
        "code_expires_at": s.get("code_expires_at") if s else None, "code_live": code_live,
        "joined": len(people), "max_people": MAX_PEOPLE, "alert_every_seconds": ALERT_EVERY_SECONDS,
        "code_ttl_seconds": CODE_TTL_SECONDS, "keep_hours": KEEP_HOURS, "next_alert_at": next_at,
        "presenter_url": presenter_url(), "alert": alert_view(repo, a) if a is not None else None,
        "as_of": clock.iso(now),
    }
    if show_code and s is not None and code_live:
        out["code"] = str(s.get("code"))
        out["join_url"] = join_link(str(s.get("code")))
    return out


# -- erasure ------------------------------------------------------------------------------------------------
def _erase_people(repo: Repo, keep_after: str | None) -> int:
    """Delete demo people (all of them, or those who joined at or before keep_after). Only the demo village's own
    record and its chat pointer go: a juror who is also enrolled in a real village keeps that enrolment."""
    n = 0
    for r in repo.list_recipients(VILLAGE_ID):
        joined = r.joined_at or ""
        if keep_after is None or not joined or joined <= keep_after:
            if repo.delete_recipient(VILLAGE_ID, r.id):
                n += 1
    return n


def _erase_alerts(repo: Repo, keep_after: str | None) -> int:
    n = 0
    for created, aid in repo.demo_alert_ids():
        if keep_after is None or created <= keep_after:
            repo.delete_demo_alert(aid, created, VILLAGE_ID)
            n += 1
    return n


def reset(repo: Repo, by: str, role: str = "officer", now: datetime | None = None) -> dict[str, int]:
    """"Reset demo": every demo person and demo alert is deleted now, and the session (its code stops working)."""
    now = now or clock.now()
    s = repo.get_demo_session()
    people, alerts = _erase_people(repo, None), _erase_alerts(repo, None)
    repo.delete_demo_session()
    if repo.get_village(VILLAGE_ID, include_demo=True) is not None:
        repo.update_village(VILLAGE_ID, open_alert_id=None, last_alert_id=None)
    _audit(repo, now, by, role, "demo_reset", f"live demo reset: {people} demo people and {alerts} demo alerts erased",
           str((s or {}).get("session_id") or ""))
    return {"people": people, "alerts": alerts}


def erase_due(repo: Repo, now: datetime | None = None) -> dict[str, int]:
    """The sweep's pass: demo people and demo alerts made KEEP_HOURS ago or earlier are deleted, and a session older
    than that is closed. Never raises."""
    now = now or clock.now()
    out = {"people": 0, "alerts": 0, "session": 0}
    try:
        cutoff = clock.iso(now - timedelta(hours=KEEP_HOURS))
        out["people"] = _erase_people(repo, cutoff)
        out["alerts"] = _erase_alerts(repo, cutoff)
        s = repo.get_demo_session()
        if s is not None and str(s.get("opened_at") or "") <= cutoff:
            repo.delete_demo_session()
            out["session"] = 1
            v = repo.get_village(VILLAGE_ID, include_demo=True)
            if v is not None and v.open_alert_id and repo.get_alert(v.open_alert_id) is None:
                repo.update_village(VILLAGE_ID, open_alert_id=None)
        if any(out.values()):
            _audit(repo, now, "pukaar-system", "system", "demo_erase",
                   f"live demo data older than {KEEP_HOURS} h erased: {out['people']} people, {out['alerts']} alerts",
                   str((s or {}).get("session_id") or ""))
    except Exception as exc:
        log(_LOG, "demo erasure failed; tried again next sweep", 40, error=str(exc)[:200])
    return out
