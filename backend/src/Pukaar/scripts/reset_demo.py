"""Reset the demo: stop any replay, remove alerts, reports, readings and
directives, put every village back to normal, and re-seed. Audit rows stay
(append-only); Telegram recipients and officer chat links stay.

    python -m Pukaar.scripts.reset_demo
"""

from __future__ import annotations

from Pukaar.scripts.seed import seed
from Pukaar.services import replay
from Pukaar.store.repo import get_repo

_KEEP_PREFIXES = ("AUDIT#", "OFFICER#")
_KEEP_SK_PREFIXES = ("META", "RECIPIENT#", "EVENT#")


def _removable(item: dict) -> bool:
    pk, sk = str(item["pk"]), str(item["sk"])
    if pk.startswith(_KEEP_PREFIXES):
        return False
    if pk.startswith("VILLAGE#"):
        return not sk.startswith(_KEEP_SK_PREFIXES)
    return True  # ALERT#, ALERTLOG, REPORTREF#, TRACK#, REPLAY


def main() -> None:
    repo = get_repo()
    replay.reset(repo)
    removed = repo.delete_where(_removable)
    for v in repo.list_villages():
        repo.update_village(v.id, level="normal", calm_sweeps=0, level_since=None, open_alert_id=None, replay=False)
    seed(repo)
    print(f"demo reset: {removed} items removed, villages back to normal")


if __name__ == "__main__":
    main()
