"""Send a labelled drill alert through the real loop, to test a real phone.

Replay alerts never reach real phones, so this is how a team member checks
Telegram or voice calls end to end: it creates one alert for a village, marked
as a drill in its decision trace and prefixed "अभ्यास (DRILL)" in the text, and
starts the real approval workflow (Step Functions on AWS). An officer approves
it in the console or from the Telegram link; every registered phone then gets
the spoken alert and the "मिल गया" button, or a call with "press 1". The
village's own level is not changed.

    python -m Pukaar.scripts.drill [village_id] [level] [channel]   # defaults: gohar watch all

channel "voice" calls only the registered voice numbers (the consented field drill in
docs/VOICE.md); "telegram" messages only Telegram; "all" (the default) uses each person's channel.
"""

from __future__ import annotations

import sys

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.ids import new_id
from Pukaar.services.decision_engine import start_workflow
from Pukaar.store.models import Alert
from Pukaar.store.repo import get_repo
from Pukaar.workflow.client import get_workflow

CHANNELS = ("all", "telegram", "voice")


def main(village_id: str = "gohar", level: str = "watch", channel: str = "all") -> None:
    channel = (channel or "all").strip().lower()
    if channel not in CHANNELS:
        raise SystemExit(f"channel must be one of {', '.join(CHANNELS)}")
    repo = get_repo()
    v = repo.get_village(village_id)
    if v is None:
        raise SystemExit(f"no village {village_id}")
    if v.open_alert_id:
        raise SystemExit(f"{village_id} already has an open alert ({v.open_alert_id}); try again after it closes")
    people = repo.list_recipients(village_id)
    telegram = [r for r in people if r.takes_telegram] if channel in {"all", "telegram"} else []
    voice = [r for r in people if r.takes_voice] if channel in {"all", "voice"} else []
    if channel == "voice":
        if not voice:
            raise SystemExit(f"no voice numbers registered for {village_id} (make voice-add)")
        unconsented = [r.name for r in voice if not r.consent]
        if unconsented:
            raise SystemExit("no recorded consent for: " + ", ".join(unconsented) + " (make voice-add ... CONSENT=)")
        if get_settings().voice_provider == "off":
            print("WARNING: PUKAAR_VOICE_PROVIDER is off here; the deployed stack's VoiceProvider decides the calls.")
    trace: dict = {"rules_fired": ["drill"], "drill": True}
    if channel != "all":
        trace["drill_channel"] = channel
    stamp = clock.iso(clock.now())
    alert = Alert(id=new_id("alr"), village_id=v.id, village_name=v.name, village_name_hi=v.name_hi, level=level,
                  status="drafting", created_at=stamp, updated_at=stamp, decision_trace=trace)
    repo.put_alert(alert)
    repo.add_timeline(alert.id, "created", f"drill ({channel}): a test alert started by hand; "
                                           f"{len(telegram)} Telegram phone(s), {len(voice)} voice number(s)")
    ok = start_workflow(repo, get_workflow(), alert)
    print(f"drill {alert.id} for {v.name} at {level} ({channel}): workflow {'started' if ok else 'FAILED to start'}; "
          f"{len(telegram)} Telegram phone(s), {len(voice)} voice number(s). "
          "Approve it in the console (or from the Telegram link).")


if __name__ == "__main__":
    main(*sys.argv[1:4])
