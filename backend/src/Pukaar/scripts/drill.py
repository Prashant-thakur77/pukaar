"""Send a labelled drill alert through the real loop, to test a real phone.

Replay alerts never reach real phones, so this is how a team member checks
Telegram end to end: it creates one alert for a village, marked as a drill in
its decision trace and prefixed "अभ्यास (DRILL)" in the text, and starts the
real approval workflow (Step Functions on AWS). An officer approves it in the
console or from the Telegram link; every registered phone then gets the
spoken alert and the "मिल गया" button. The village's own level is not changed.

    python -m Pukaar.scripts.drill [village_id] [level]     # defaults: gohar watch
"""

from __future__ import annotations

import sys

from Pukaar.core import clock
from Pukaar.core.ids import new_id
from Pukaar.services.decision_engine import start_workflow
from Pukaar.store.models import Alert
from Pukaar.store.repo import get_repo
from Pukaar.workflow.client import get_workflow


def main(village_id: str = "gohar", level: str = "watch") -> None:
    repo = get_repo()
    v = repo.get_village(village_id)
    if v is None:
        raise SystemExit(f"no village {village_id}")
    if v.open_alert_id:
        raise SystemExit(f"{village_id} already has an open alert ({v.open_alert_id}); try again after it closes")
    real = [r for r in repo.list_recipients(village_id) if r.channel == "telegram"]
    stamp = clock.iso(clock.now())
    alert = Alert(id=new_id("alr"), village_id=v.id, village_name=v.name, village_name_hi=v.name_hi, level=level,
                  status="drafting", created_at=stamp, updated_at=stamp,
                  decision_trace={"rules_fired": ["drill"], "drill": True})
    repo.put_alert(alert)
    repo.add_timeline(alert.id, "created", f"drill: a test alert started by hand; {len(real)} registered phone(s)")
    ok = start_workflow(repo, get_workflow(), alert)
    print(f"drill {alert.id} for {v.name} at {level}: workflow {'started' if ok else 'FAILED to start'}; "
          f"{len(real)} registered phone(s). Approve it in the console (or from the Telegram link).")


if __name__ == "__main__":
    main(*sys.argv[1:3])
