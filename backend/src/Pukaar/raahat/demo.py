"""Demo evidence for the pradhan's attestation (make raahat-demo-photo, demo stack only).

The pradhan attests from a verified photo report of their own village. In a replay there is none, so this files
one: a photo labelled DEMO in Hindi and English, as a replay report (never on the live village page, never able to
raise a live level), verified by the demo officer. The live report route (POST /reports) is never used for it.
File it after the replay has started: starting a replay clears the last one's items. Refused on a prod stack.
"""

from __future__ import annotations

import sys
from pathlib import Path

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.ids import new_id
from Pukaar.store.models import Report
from Pukaar.store.repo import Repo

TEXT = "DEMO photo for the Raahat demo: replay of the July 2023 Beas flood, not a real flood today."


def photo_report(repo: Repo, village_id: str, photo: bytes, *, by: str) -> str:
    from Pukaar.services import storage

    if get_settings().stage == "prod":
        raise RuntimeError("demo evidence is never filed on a prod stack")
    rid = new_id("rep")
    key = f"reports/{rid}/photo.jpg"
    storage.put_bytes(key, photo, "image/jpeg")
    repo.put_report(Report(id=rid, village_id=village_id, created_at=clock.iso(clock.now()), text=TEXT,
                           report_type="water_rising", state="verified", verified_by=by, photo_key=key,
                           photo_description="Labelled demo image (replay); not a photograph of a flood",
                           replay=True, track_code=f"DEMO{rid[-4:].upper()}"))
    return rid


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m Pukaar.raahat.demo <village id> <photo.jpg>")
        return 2
    from Pukaar.store.repo import get_repo

    rid = photo_report(get_repo(), argv[0], Path(argv[1]).read_bytes(), by="officer1")
    print(f"replay photo report {rid} in {argv[0]}, verified by officer1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
