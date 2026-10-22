"""Register voice-call recipients and print the Exotel flow URLs (docs/VOICE.md).

    python -m Pukaar.scripts.voice add <village> "<name>" <+91XXXXXXXXXX> "<consent>" [role] [chat id]
    python -m Pukaar.scripts.voice list <village>
    python -m Pukaar.scripts.voice remove <village> <recipient id>
    python -m Pukaar.scripts.voice urls <api url>

add: a new voice-only recipient (id v_<ulid>); with a Telegram chat id, that existing Telegram
recipient takes calls too (channel "both"). Consent is required: how and when the household
agreed, e.g. "verbal, field visit 2026-10-25, Asha Devi". The number is stored like the Telegram
chat id (DynamoDB, encrypted at rest) and is printed masked; it never appears on a public route.

urls: the three URLs to paste into the Exotel flow, with the webhook key from SSM. Treat the
output as a secret.
"""

from __future__ import annotations

import sys

from Pukaar.core.ids import new_id
from Pukaar.delivery import voice
from Pukaar.store.models import Recipient
from Pukaar.store.repo import get_repo


def add(village_id: str, name: str, phone: str, consent: str, role: str = "villager", chat_id: str = "") -> None:
    repo = get_repo()
    if repo.get_village(village_id) is None:
        raise SystemExit(f"no village {village_id}")
    if not consent.strip():
        raise SystemExit("record how and when the household agreed to be called (CONSENT=...)")
    if chat_id:
        existing = repo.get_recipient(village_id, chat_id)
        if existing is None or not existing.takes_telegram:
            raise SystemExit(f"no Telegram recipient {chat_id} in {village_id}")
        r = existing.model_copy(update={"channel": "both", "phone": phone, "consent": consent.strip()})
        r = Recipient.model_validate(r.model_dump())
    else:
        r = Recipient.model_validate({"id": new_id("v"), "village_id": village_id, "name": name.strip(), "role": role,
                                      "channel": "voice", "phone": phone, "consent": consent.strip()})
    dup = [x.id for x in repo.list_recipients(village_id) if x.phone == r.phone and x.id != r.id]
    if dup:
        raise SystemExit(f"this number is already registered in {village_id} as {dup[0]}")
    repo.put_recipient(r)
    print(f"{r.id}  {r.name}  {r.channel}  {voice.mask_phone(r.phone)}  consent: {r.consent}")


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
        repo.delete_recipient(village_id, recipient_id)
        print(f"{recipient_id}: removed")


def urls(api_url: str) -> None:
    key = voice.webhook_key()
    if not key:
        raise SystemExit("SSM /pukaar/voice_webhook_key is not set (docs/VOICE.md, step 3)")
    base = api_url.rstrip("/")
    print(f"Greeting (dynamic URL):  {base}/voice/exotel/flow?k={key}&part=greeting")
    print(f"Gather (dynamic URL):    {base}/voice/exotel/flow?k={key}&part=menu")
    print(f"Passthru URL:            {base}/voice/exotel/gather?k={key}")


def main(argv: list[str]) -> None:
    if not argv:
        raise SystemExit(__doc__)
    cmd, args = argv[0], argv[1:]
    if cmd == "add" and len(args) >= 4:
        add(*args[:6])
    elif cmd == "list" and len(args) == 1:
        list_(args[0])
    elif cmd == "remove" and len(args) == 2:
        remove(*args)
    elif cmd == "urls" and len(args) == 1:
        urls(args[0])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
