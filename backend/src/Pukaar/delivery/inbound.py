"""Inbound calls: missed-call and IVR self-enrolment, and "report what you see" (docs/VOICE.md, "Inbound").

EWS1294 in Cambodia grew mainly by people calling a short code and choosing their place on the keypad
(61% of subscribers in 2022). This is that path for Pukaar, on the same voice providers and behind the same
switch (PUKAAR_VOICE_PROVIDER: off by default, so every inbound route refuses until a DDMA turns voice on).

One number, one menu:

    1  join the flood alerts: the notice is read (what is kept, why, how long, how to leave), "1" agrees,
       then the village code on the keypad (Village.ivr_code, on the village card) and "1" to confirm.
       Stored: the caller id as the number, channel voice, enrolled_via "ivr", by "self", and the consent
       record (the key press after NOTICE_VERSION, and when). Nothing is stored before the "1" that agrees.
    2  water is rising     } then the village code and a 20-second recording. A report is made with the
    3  a road is blocked   } caller's verified role: the caller id matched to someone enrolled in that village.
                             A relay's (pradhan, gauge reader, task force) report is auto-verified and the
                             village is evaluated at once, so the officer is asked without waiting for a second
                             report; the duty officers are told on Telegram and Web Push. An unknown caller's
                             report waits in the officers' queue like any unverified report.
    9  leave: the village code, then "1": the number is taken off that village (erased later, privacy.py).

A missed call (Settings.ivr_missed_call_callback, off by default: each callback is a billed call): the call is
rejected unanswered, so it costs the caller nothing, and Pukaar calls back into the same menu, at most once
per number a day.

The provider adapters are thin (api/routers/voice.py): this module keeps the session (Repo INBOUND#<call id>,
two hours) and answers each step with a Prompt: words to say, then a keypad gather, a recording, or the end.
The caller's number lives in the session only while the call runs and is deleted at the end; it is never
logged (voice.mask_phone).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.ids import new_id
from Pukaar.core.log import get_logger, log, metric
from Pukaar.delivery.voice import mask_phone
from Pukaar.store.models import RELAY_ROLES, AuditRow, Recipient, Village
from Pukaar.store.repo import Repo

_LOG = get_logger("inbound")

NOTICE_VERSION = "ivr-notice-v1"
RECORD_SECONDS = 20
CODE_DIGITS = 6
MAX_TRIES = 2
REPORT_KINDS = {"2": ("water_rising", "high", "पानी बढ़ रहा है", "water rising"),
                "3": ("road_cut", "medium", "रास्ता या पुल बंद है", "road or bridge blocked")}

MENU_HI = ("पुकार, ज़िला आपदा प्रबंधन की बाढ़ चेतावनी सेवा। बाढ़ की चेतावनी के लिए जुड़ने को एक दबाएँ। "
           "नदी या नाले का पानी बढ़ता दिखे तो दो दबाएँ। रास्ता या पुल बंद हो तो तीन दबाएँ। "
           "सेवा छोड़ने के लिए नौ दबाएँ।")


def notice_hi(days: int) -> str:
    return ("सूचना: जुड़ने पर हम आपका फ़ोन नंबर और आपका गाँव रखेंगे। केवल बाढ़ की चेतावनी, सब-ठीक का संदेश और "
            "आप सुरक्षित हैं, यह पूछने के लिए कॉल करेंगे, किसी और काम के लिए नहीं। जब तक आप जुड़े हैं तब तक; "
            f"छोड़ने पर नंबर हटा दिया जाता है और पुराने रिकॉर्ड से {days} दिन में। कभी भी छोड़ें: इसी नंबर पर कॉल "
            "करके नौ दबाएँ, या अपने प्रधान को बताएँ। सहमत हैं तो एक दबाएँ। नहीं तो फ़ोन रख दें, कुछ नहीं रखा जाएगा।")


CODE_HI = "अपने गाँव का कोड डालें, फिर हैश दबाएँ। कोड गाँव के कार्ड पर है, या प्रधान से पूछें।"
CODE_AGAIN_HI = "यह कोड नहीं मिला। फिर से गाँव का कोड डालें, फिर हैश दबाएँ।"
NOT_FOUND_HI = "कोड नहीं मिला। कृपया प्रधान से कोड लेकर फिर कॉल करें। धन्यवाद।"
NOT_AGREED_HI = "ठीक है। आपके बारे में कुछ नहीं रखा गया। धन्यवाद।"
ENROLLED_HI = ("आप {village} की बाढ़ चेतावनियों के लिए जुड़ गए हैं। चेतावनी आने पर इसी नंबर पर कॉल आएगी, सुनकर एक "
               "दबाएँ। आपात स्थिति में 112 पर कॉल करें। धन्यवाद।")
ALREADY_HI = "यह नंबर {village} के लिए पहले से जुड़ा है। धन्यवाद।"
RECORD_HI = "बीप के बाद बीस सेकंड में बताइए आप क्या देख रहे हैं और कहाँ। फिर फ़ोन रख दें।"
REPORT_THANKS_HI = "धन्यवाद, आपकी सूचना अधिकारियों तक पहुँच गई है। ख़तरा हो तो ऊँची सुरक्षित जगह जाएँ, आपात में 112।"
LEFT_HI = "यह नंबर {village} की चेतावनियों से हटा दिया गया। फिर जुड़ने के लिए इसी नंबर पर कॉल करके एक दबाएँ। धन्यवाद।"
NOT_ENROLLED_HI = "यह नंबर {village} के लिए जुड़ा नहीं था; हटाने को कुछ नहीं है। धन्यवाद।"
GOODBYE_HI = "धन्यवाद। आपात स्थिति में 112 पर कॉल करें।"
NO_CALLER_HI = "आपका नंबर नहीं दिखा, इसलिए जुड़ना संभव नहीं। कृपया प्रधान से संपर्क करें। धन्यवाद।"


def confirm_hi(village_hi: str, district_hi: str, leaving: bool = False) -> str:
    what = "हटाने" if leaving else "जुड़ने"
    return f"आपने {village_hi}, {district_hi} चुना। {what} के लिए एक दबाएँ, कोड बदलने के लिए दो दबाएँ।"


@dataclass(frozen=True)
class Prompt:
    """What the caller hears next, then: a keypad gather (digits > 0), a recording, or the end."""

    say: str
    digits: int = 0  # how many keys to gather; 0 = no gather
    finish_on_hash: bool = False
    record_seconds: int = 0
    end: bool = False

    @property
    def gathers(self) -> bool:
        return self.digits > 0

    @property
    def records(self) -> bool:
        return self.record_seconds > 0


MENU = Prompt(MENU_HI, digits=1)


def live(provider: str) -> bool:
    """Inbound calls are answered only for the provider voice is switched to (off: never)."""
    return get_settings().voice_provider == provider


def caller_number(raw: str | None) -> str | None:
    """The caller id as E.164: Plivo sends 919812345678, Exotel 09812345678; None when hidden or not a mobile."""
    from Pukaar.services.enrolment import EnrolError, normalise_phone

    try:
        return normalise_phone(re.sub(r"[^\d+]", "", raw or "")) if raw else None
    except EnrolError:
        return None


def village_by_code(repo: Repo, code: str) -> Village | None:
    """The village whose keypad code (Village.ivr_code, or its verified LGD village code) is `code`."""
    code = re.sub(r"\D", "", code or "")
    if not code:
        return None
    hits = [v for v in repo.list_villages() if code in {v.ivr_code, v.lgd_village_code}]
    return hits[0] if len(hits) == 1 else None


def _district_hi(v: Village) -> str:
    from Pukaar.services.cap import district_hi

    return district_hi(v)


def _session(repo: Repo, call_id: str, caller: str | None, provider: str) -> dict[str, Any]:
    s = repo.get_inbound(call_id)
    if s is None:
        s = {"stage": "menu", "caller": caller or "", "provider": provider, "tries": 0, "started": clock.iso(clock.now())}
        repo.put_inbound(call_id, s)
    elif caller and not s.get("caller"):
        s["caller"] = caller
    return s


def _save(repo: Repo, call_id: str, s: dict[str, Any], **changes: Any) -> dict[str, Any]:
    s = {**s, **changes}
    repo.put_inbound(call_id, s)
    return s


def _finish(repo: Repo, call_id: str, say: str) -> Prompt:
    repo.delete_inbound(call_id)
    return Prompt(say, end=True)


def current(repo: Repo, call_id: str, caller: str | None, provider: str) -> Prompt:
    """The prompt for where the call is now (a provider asks again after a timeout or a redirect)."""
    s = _session(repo, call_id, caller, provider)
    stage = s["stage"]
    if stage == "menu":
        return MENU
    if stage == "notice":
        return Prompt(notice_hi(get_settings().unlinked_retention_days), digits=1)
    if stage in {"village", "report_village", "leave_village"}:
        return Prompt(CODE_AGAIN_HI if s.get("tries") else CODE_HI, digits=CODE_DIGITS, finish_on_hash=True)
    if stage in {"confirm", "leave_confirm"}:
        v = repo.get_village(str(s.get("village_id") or ""))
        if v is None:
            return _finish(repo, call_id, NOT_FOUND_HI)
        return Prompt(confirm_hi(v.name_hi, _district_hi(v), stage == "leave_confirm"), digits=1)
    if stage == "record":
        return Prompt(RECORD_HI, record_seconds=RECORD_SECONDS)
    return _finish(repo, call_id, GOODBYE_HI)


def press(repo: Repo, call_id: str, caller: str | None, digits: str | None, provider: str) -> Prompt:
    """A key (or keys) after a gather: the next prompt."""
    s = _session(repo, call_id, caller, provider)
    d = re.sub(r"[^\d*#]", "", (digits or "").strip().strip('"')).rstrip("#")
    stage = s["stage"]
    if stage == "menu":
        if d == "1":
            _save(repo, call_id, s, stage="notice", tries=0)
            return current(repo, call_id, caller, provider)
        if d in REPORT_KINDS:
            _save(repo, call_id, s, stage="report_village", report_key=d, tries=0)
            return current(repo, call_id, caller, provider)
        if d == "9":
            _save(repo, call_id, s, stage="leave_village", tries=0)
            return current(repo, call_id, caller, provider)
        return _retry(repo, call_id, s, MENU)
    if stage == "notice":
        if d != "1":
            return _finish(repo, call_id, NOT_AGREED_HI)
        if not s.get("caller"):
            return _finish(repo, call_id, NO_CALLER_HI)
        _save(repo, call_id, s, stage="village", tries=0, agreed_at=clock.iso(clock.now()))
        return current(repo, call_id, caller, provider)
    if stage in {"village", "report_village", "leave_village"}:
        v = village_by_code(repo, d)
        if v is None:
            if int(s.get("tries") or 0) + 1 >= MAX_TRIES:
                return _finish(repo, call_id, NOT_FOUND_HI)
            _save(repo, call_id, s, tries=int(s.get("tries") or 0) + 1)
            return current(repo, call_id, caller, provider)
        nxt = {"village": "confirm", "report_village": "record", "leave_village": "leave_confirm"}[stage]
        _save(repo, call_id, s, stage=nxt, village_id=v.id, tries=0)
        return current(repo, call_id, caller, provider)
    if stage == "confirm":
        if d == "2":
            _save(repo, call_id, s, stage="village", tries=0)
            return current(repo, call_id, caller, provider)
        if d != "1":
            return _finish(repo, call_id, NOT_AGREED_HI)
        return _enrol(repo, call_id, s)
    if stage == "leave_confirm":
        if d == "2":
            _save(repo, call_id, s, stage="leave_village", tries=0)
            return current(repo, call_id, caller, provider)
        if d != "1":
            return _finish(repo, call_id, GOODBYE_HI)
        return _leave(repo, call_id, s)
    return current(repo, call_id, caller, provider)


def _retry(repo: Repo, call_id: str, s: dict[str, Any], prompt: Prompt) -> Prompt:
    tries = int(s.get("tries") or 0) + 1
    if tries >= MAX_TRIES:
        return _finish(repo, call_id, GOODBYE_HI)
    _save(repo, call_id, s, tries=tries)
    return prompt


def _enrol(repo: Repo, call_id: str, s: dict[str, Any]) -> Prompt:
    v = repo.get_village(str(s.get("village_id") or ""))
    phone = str(s.get("caller") or "")
    if v is None or not phone:
        return _finish(repo, call_id, NOT_FOUND_HI if v is None else NO_CALLER_HI)
    if any(r.phone == phone for r in repo.list_recipients(v.id)):
        return _finish(repo, call_id, ALREADY_HI.format(village=v.name_hi))
    now = clock.iso(clock.now())
    consent = (f"ivr keypress 1 after the spoken notice ({NOTICE_VERSION}) at {s.get('agreed_at') or now}, "
               f"village confirmed by keypad at {now}; caller id as the number")
    person = Recipient(id=new_id("v"), village_id=v.id, name="फ़ोन से जुड़े · joined by phone", channel="voice",
                       phone=phone, consent=consent, enrolled_via="ivr", enrolled_by="self")
    repo.put_recipient(person)
    repo.append_audit(AuditRow(at=now, id=new_id("aud"), actor="ivr-caller", role="villager",
                               action="household_enrolled", resource=f"recipient:{v.id}/{person.id}", decision="allow",
                               reason=f"ivr self-enrolment: voice {mask_phone(phone)}; consent: {consent}"))
    metric("IvrEnrolled", 1, Village=v.id)
    log(_LOG, "enrolled by phone", village_id=v.id, recipient=person.id)
    return _finish(repo, call_id, ENROLLED_HI.format(village=v.name_hi))


def _leave(repo: Repo, call_id: str, s: dict[str, Any]) -> Prompt:
    from Pukaar.services import privacy

    v = repo.get_village(str(s.get("village_id") or ""))
    phone = str(s.get("caller") or "")
    if v is None or not phone:
        return _finish(repo, call_id, NOT_FOUND_HI if v is None else NO_CALLER_HI)
    gone = 0
    for r in repo.list_recipients(v.id):
        if r.phone != phone or r.role == "officer":
            continue
        if r.channel == "both":  # Telegram stays: they leave the calls only
            repo.put_recipient(r.model_copy(update={"channel": "telegram", "phone": None}))
            gone += 1
        elif privacy.remove_recipient(repo, v.id, r.id, "left by calling the IVR and pressing 9"):
            gone += 1
    if gone:
        repo.append_audit(AuditRow(at=clock.iso(clock.now()), id=new_id("aud"), actor="ivr-caller", role="villager",
                                   action="household_left", resource=f"village:{v.id}", decision="allow",
                                   reason=f"left by IVR (9): {mask_phone(phone)}"))
    return _finish(repo, call_id, (LEFT_HI if gone else NOT_ENROLLED_HI).format(village=v.name_hi))


def recorded(repo: Repo, call_id: str, caller: str | None, recording_url: str | None, provider: str,
             *, workflow: Any = None, fetch_audio: Any = None) -> Prompt:
    """The recording finished (or the caller hung up during it): the report is made either way."""
    s = repo.get_inbound(call_id)
    if s is None or s.get("stage") != "record":
        return Prompt(GOODBYE_HI, end=True)
    v = repo.get_village(str(s.get("village_id") or ""))
    if v is None:
        return _finish(repo, call_id, NOT_FOUND_HI)
    report(repo, v, str(s.get("report_key") or "2"), str(s.get("caller") or caller or "") or None, recording_url,
           workflow=workflow, fetch_audio=fetch_audio)
    return _finish(repo, call_id, REPORT_THANKS_HI)


def caller_role(repo: Repo, village: Village, phone: str | None) -> tuple[str, Recipient | None]:
    """The caller's verified role in this village: the caller id matched to an enrolled number."""
    if not phone:
        return "unknown", None
    person = next((r for r in repo.list_recipients(village.id) if r.phone == phone), None)
    return (person.role if person else "unknown"), person


def report(repo: Repo, village: Village, kind: str, phone: str | None, recording_url: str | None, *,
           workflow: Any = None, fetch_audio: Any = None) -> Any:
    """Make the report. A relay's is auto-verified and the village evaluated now; the duty officers are told."""
    from Pukaar.services import report_guard
    from Pukaar.services.reports import intake

    report_type, severity, what_hi, what_en = REPORT_KINDS.get(kind, REPORT_KINDS["2"])
    role, person = caller_role(repo, village, phone)
    audio = None
    if recording_url:
        try:
            audio = (fetch_audio or _fetch_recording)(recording_url)
        except Exception as exc:
            log(_LOG, "recording fetch failed", 30, error=type(exc).__name__)
    text = f"फ़ोन पर सूचना (IVR): {what_hi}।"
    r = intake(repo, village, text=text, audio=audio, reporter_name=person.name if person else None,
               source=report_guard.make_source(None, f"ivr:{phone}" if phone else None, None))
    relay = role in RELAY_ROLES
    flags = [f for f in r.flags if f != report_guard.FLAG_SOURCE_UNKNOWN] + [
        "ivr_report", f"caller_role:{role}", "caller_id_matched" if person else "caller_unknown"]
    if recording_url and audio is None:
        flags.append("recording_unavailable")
    if not recording_url:
        flags.append("no_recording")
    fields: dict[str, Any] = {"report_type": report_type, "severity": severity, "flags": flags,
                              "parser_source": "ivr-keypad",
                              "summary_en": f"Phone report (IVR): {what_en} in {village.name}, from "
                                            f"{'a ' + role.replace('_', ' ') + ' (caller id matched)' if person else 'an unknown caller'}."}
    if relay and not r.hold_reason and r.state in {"unverified", "transcribing"}:
        fields.update(state="verified_auto", previous_state=r.state, verified_by=f"auto:ivr-relay:{role}")
    elif r.state == "transcribing":
        fields.update(state="unverified", previous_state="transcribing")
    r = repo.update_report(r.id, **fields)
    repo.append_audit(AuditRow(at=clock.iso(clock.now()), id=new_id("aud"), actor="ivr-caller", role="villager",
                               action="ivr_report", resource=f"report:{r.id}", decision="allow",
                               reason=f"{what_en} in {village.name} by a caller whose role is {role}"
                                      + ("; auto-verified (relay)" if r.state == "verified_auto" else "")))
    metric("IvrReport", 1, Village=village.id, Relay=str(relay).lower())
    _tell_duty(repo, village, r, role, what_hi, what_en)
    if r.state == "verified_auto":
        from Pukaar.services.decision_engine import recompute_village

        try:
            recompute_village(repo, repo.get_village(village.id) or village, workflow=workflow)
        except Exception as exc:  # the report is kept; the next sweep reads it
            log(_LOG, "recompute after relay report failed", 40, village_id=village.id, error=str(exc)[:200])
    return r


def _fetch_recording(url: str) -> tuple[bytes, str] | None:
    """The provider's recording (Plivo: a public mp3 URL; Exotel: the account's API key and token)."""
    from Pukaar.delivery import voice

    if not url.startswith("https://"):
        return None
    auth = None
    if get_settings().voice_provider == "exotel":
        from Pukaar.delivery import exotel

        creds = exotel.credentials()
        auth = (creds.api_key, creds.token) if creds else None
    client, owned = voice.http_client()
    try:
        r = client.get(url, auth=auth, timeout=8) if auth else client.get(url, timeout=8)
        if r.status_code >= 400 or not r.content or len(r.content) > 5_000_000:
            return None
        return r.content, (r.headers.get("content-type") or "audio/mpeg").split(";")[0]
    finally:
        if owned:
            client.close()


def _tell_duty(repo: Repo, village: Village, r: Any, role: str, what_hi: str, what_en: str) -> None:
    """The duty officers of the district hear of a phone report at once (Telegram and Web Push); never raises."""
    from Pukaar.delivery import telegram
    from Pukaar.services import officer_push, roster

    try:
        duty = roster.chain_for(repo, village)
        who_en = f"a {role.replace('_', ' ')} (caller id matched)" if role != "unknown" else "an unknown caller"
        tag = " Auto-verified: the village is being evaluated now." if r.state == "verified_auto" else ""
        text = (f"पुकार: {village.name_hi} से फ़ोन पर सूचना: {what_hi}।\n"
                f"Pukaar: phone report from {village.name} ({village.district}): {what_en}, from {who_en}.{tag} "
                f"Report {r.id}: {get_settings().web_url}/console/reports")
        for officer in duty.chain:
            chat = repo.get_officer_chat(officer)
            if chat and telegram.configured():
                try:
                    telegram.send_text(chat, text)
                except Exception as exc:
                    log(_LOG, "duty telegram failed", 30, error=str(exc)[:200])
            officer_push.send_to_user(repo, officer, {
                "kind": "info", "title": f"फ़ोन पर सूचना · Phone report: {village.name}",
                "body": f"{what_en}, from {who_en}", "tag": f"report-{r.id}", "data": {"url": "/console/reports"}},
                ttl=3600, urgency="high", kind="report")
    except Exception as exc:
        log(_LOG, "telling the duty officers failed", 30, error=str(exc)[:200])


# -- missed calls ---------------------------------------------------------------------------------------
def missed(repo: Repo, caller: str | None, provider: str, *, place: Any = None) -> str:
    """A missed call: call back into the menu when the DDMA turned callbacks on; at most once per number a day.
    Returns what happened: off | no_caller | limited | placed | failed."""
    if not get_settings().ivr_missed_call_callback:
        return "off"
    if not caller:
        return "no_caller"
    import hashlib

    day = clock.iso(clock.now())[:10]
    digest = hashlib.sha256(f"pukaar-missed:{caller}".encode()).hexdigest()[:24]
    if not repo.claim_once("missedcall", f"{day}#{digest}", ttl_seconds=2 * 86400):
        return "limited"
    try:
        (place or place_callback)(caller, provider)
    except Exception as exc:
        log(_LOG, "missed-call callback failed", 30, error=str(exc)[:200])
        return "failed"
    metric("IvrCallback", 1)
    return "placed"


def place_callback(phone: str, provider: str) -> str:
    """One outbound call into the inbound menu. Returns the provider's call id."""
    from Pukaar.delivery import voice

    client, owned = voice.http_client()
    try:
        if provider == "plivo":
            from Pukaar.delivery import plivo

            creds = plivo.credentials()
            if creds is None:
                raise voice.VoiceUnavailable("Plivo credentials unavailable")
            body = {"from": creds.caller_id.lstrip("+"), "to": phone.lstrip("+"),
                    "answer_url": voice.callback_url("/voice/plivo/inbound"), "answer_method": "POST",
                    "hangup_url": voice.callback_url("/voice/plivo/inbound-hangup"), "hangup_method": "POST",
                    "ring_timeout": get_settings().voice_ring_timeout_seconds, "time_limit": 300}
            r = client.post(f"{plivo.API}/Account/{creds.auth_id}/Call/", json=body,
                            auth=(creds.auth_id, creds.auth_token))
            data = r.json() if r.content else {}
            if r.status_code >= 400:
                raise voice.VoiceError(f"Plivo {r.status_code}", "provider_error")
            uid = data.get("request_uuid")
            return str(uid[0] if isinstance(uid, list) else uid)
        if provider == "exotel":
            from Pukaar.core.secrets import get_secret
            from Pukaar.delivery import exotel

            creds = exotel.credentials()
            app = get_secret("exotel_inbound_app_id")
            if creds is None or not app:
                raise voice.VoiceUnavailable("Exotel credentials or exotel_inbound_app_id unavailable")
            data = {"From": phone, "CallerId": creds.caller_id, "Url": exotel.flow_url(creds.sid, app),
                    "CallType": "trans", "TimeOut": str(get_settings().voice_ring_timeout_seconds), "TimeLimit": "300"}
            r = client.post(f"https://{get_settings().exotel_api_host}/v1/Accounts/{creds.sid}/Calls/connect.json",
                            data=data, auth=(creds.api_key, creds.token))
            if r.status_code >= 400:
                raise voice.VoiceError(f"Exotel {r.status_code}", "provider_error")
            return str((r.json().get("Call") or {}).get("Sid"))
        raise voice.VoiceUnavailable("voice is off")
    finally:
        if owned:
            client.close()
