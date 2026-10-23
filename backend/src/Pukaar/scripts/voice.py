"""Register voice-call recipients and print the Exotel flow URLs (docs/VOICE.md).

    python -m Pukaar.scripts.voice add <village> "<name>" <+91XXXXXXXXXX> "<consent>" [role] [chat id]
    python -m Pukaar.scripts.voice role <village> <recipient id or Telegram chat id> <role>
    python -m Pukaar.scripts.voice list <village>
    python -m Pukaar.scripts.voice remove <village> <recipient id>
    python -m Pukaar.scripts.voice urls <api url>
    python -m Pukaar.scripts.voice codes
    python -m Pukaar.scripts.voice officer <username> <+91XXXXXXXXXX | remove | show>

add: a new voice-only recipient (id v_<ulid>); with a Telegram chat id, that existing Telegram
recipient takes calls too (channel "both"), and takes the role if one is given (an empty role keeps
theirs). Consent is required: how and when the household
agreed, e.g. "verbal, field visit 2026-10-25, Asha Devi". The number is stored like the Telegram
chat id (DynamoDB, encrypted at rest) and is printed masked; it never appears on a public route.

role: make a registered person (a Telegram chat id, or a v_... id) a relay: pradhan, gauge_reader or
task_force; or villager again. A pradhan who registered with /start <village> is a villager until this
is run (or an officer sets it in the console). Audited ("recipient_role_changed", actor "cli").

urls: the URLs to paste into the Exotel flows (the alert call, and the inbound menu people call to join
or report), and Plivo's inbound URLs, with the webhook key from SSM. Treat the output as a secret.

codes: each village's keypad code for joining by phone (Village.ivr_code), for the village card.

officer: the duty officer's phone for the wake-up call (delivery/officer_call.py): when an approval
waits and the officer has not opened the link, they are phoned at the nudge. The call only sends the
link again; it never approves. Printed masked; kept in the table like a recipient's number.
"""

from __future__ import annotations

import sys

from Pukaar.core.config import get_settings
from Pukaar.core.ids import new_id
from Pukaar.delivery import voice
from Pukaar.services import recipients
from Pukaar.store.models import Recipient
from Pukaar.store.repo import get_repo


def _role(role: str) -> str:
    try:
        return recipients.check_role(role)
    except recipients.RoleError as exc:
        raise SystemExit(str(exc)) from None


def add(village_id: str, name: str, phone: str, consent: str, role: str = "", chat_id: str = "") -> None:
    repo = get_repo()
    if repo.get_village(village_id) is None:
        raise SystemExit(f"no village {village_id}")
    if not consent.strip():
        raise SystemExit("record how and when the household agreed to be called (CONSENT=...)")
    role = _role(role) if role.strip() else ""
    if chat_id:
        existing = repo.get_recipient(village_id, chat_id)
        if existing is None or not existing.takes_telegram:
            raise SystemExit(f"no Telegram recipient {chat_id} in {village_id}")
        r = existing.model_copy(update={"channel": "both", "phone": phone, "consent": consent.strip()})
        r = Recipient.model_validate(r.model_dump())
    else:
        r = Recipient.model_validate({"id": new_id("v"), "village_id": village_id, "name": name.strip(),
                                      "role": role or "villager", "channel": "voice", "phone": phone,
                                      "consent": consent.strip()})
    dup = [x.id for x in repo.list_recipients(village_id) if x.phone == r.phone and x.id != r.id]
    if dup:
        raise SystemExit(f"this number is already registered in {village_id} as {dup[0]}")
    repo.put_recipient(r)
    if chat_id and role:  # ROLE=pradhan with CHAT=: the Telegram pradhan becomes a relay too (audited)
        r = recipients.set_role(repo, village_id, r.id, role, actor="cli", actor_role="operator")
    print(f"{r.id}  {r.name}  {r.role}  {r.channel}  {voice.mask_phone(r.phone)}  consent: {r.consent}")


def role(village_id: str, recipient_id: str, new_role: str) -> None:
    repo = get_repo()
    if repo.get_village(village_id) is None:
        raise SystemExit(f"no village {village_id}")
    try:
        r = recipients.set_role(repo, village_id, recipient_id, _role(new_role), actor="cli", actor_role="operator")
    except KeyError:
        raise SystemExit(f"no recipient {recipient_id} in {village_id} (a Telegram recipient's id is the chat id; "
                         f"make voice-list or the console's people list shows the others)") from None
    except recipients.RoleError as exc:
        raise SystemExit(str(exc)) from None
    print(f"{r.id}  {r.name}  {r.role}  {r.channel}")


def list_(village_id: str) -> None:
    for r in get_repo().list_recipients(village_id):
        if r.takes_voice:
            print(f"{r.id}  {r.name}  {r.role}  {r.channel}  {voice.mask_phone(r.phone)}  consent: {r.consent or '-'}")


def remove(village_id: str, recipient_id: str) -> None:
    repo = get_repo()
    r = repo.get_recipient(village_id, recipient_id)
    if r is None:
        raise SystemExit(f"no recipient {recipient_id} in {village_id}")
    if r.channel == "both":
        repo.put_recipient(r.model_copy(update={"channel": "telegram", "phone": None, "consent": None}))
        print(f"{recipient_id}: calls stopped; Telegram kept")
    else:
        from Pukaar.services import privacy

        privacy.remove_recipient(repo, village_id, recipient_id, "removed by the operator (scripts/voice.py)")
        print(f"{recipient_id}: removed; what is left of them (delivery rows, their number in reports) is erased "
              f"after {get_settings().unlinked_retention_days} days (docs/SECURITY.md, DPDP)")


def urls(api_url: str) -> None:
    key = voice.webhook_key()
    if not key:
        raise SystemExit("SSM /pukaar/voice_webhook_key is not set (docs/VOICE.md, step 3)")
    base = api_url.rstrip("/")
    print(f"Greeting (dynamic URL):  {base}/voice/exotel/flow?k={key}&part=greeting")
    print(f"Gather (dynamic URL):    {base}/voice/exotel/flow?k={key}&part=menu")
    print(f"Passthru URL:            {base}/voice/exotel/gather?k={key}")
    # The inbound flow (people calling in to join or to report; docs/VOICE.md "Inbound calls").
    print("Inbound flow (the number people call):")
    for part, applet in (("prompt", "Gather (dynamic URL)"), ("key", "Passthru after the Gather"),
                         ("next", "Passthru: record or close"), ("recorded", "Passthru after Record"),
                         ("closing", "Greeting (dynamic URL)"), ("missed", "Passthru in the missed-call flow")):
        print(f"  {applet + ':':34} {base}/voice/exotel/inbound/{part}?k={key}")
    print(f"Plivo inbound answer URL:  {base}/voice/plivo/inbound?k={key}")
    print(f"Plivo inbound hangup URL:  {base}/voice/plivo/inbound-hangup?k={key}")


def codes() -> None:
    """The keypad code of each village for joining by phone (print it on the village card)."""
    for v in get_repo().list_villages():
        print(f"{v.ivr_code or '-':>6}  {v.id}  {v.name} ({v.district})")


def officer(username: str, phone: str) -> None:
    repo = get_repo()
    if phone == "remove":
        repo.delete_officer_phone(username)
        print(f"{username}: no wake-up calls")
        return
    if phone != "show":
        try:
            repo.put_officer_phone(username, phone)
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
    print(f"{username}  {voice.mask_phone(repo.get_officer_phone(username))}")


def main(argv: list[str]) -> None:
    if not argv:
        raise SystemExit(__doc__)
    cmd, args = argv[0], argv[1:]
    if cmd == "add" and len(args) >= 4:
        add(*args[:6])
    elif cmd == "role" and len(args) == 3:
        role(*args)
    elif cmd == "list" and len(args) == 1:
        list_(args[0])
    elif cmd == "remove" and len(args) == 2:
        remove(*args)
    elif cmd == "urls" and len(args) == 1:
        urls(args[0])
    elif cmd == "codes" and not args:
        codes()
    elif cmd == "officer" and len(args) == 2:
        officer(*args)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
