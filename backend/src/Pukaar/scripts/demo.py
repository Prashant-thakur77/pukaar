"""The live jury demo from the command line (docs/DEMO_LIVE.md; services/demo.py).

    python -m Pukaar.scripts.demo open    # open the session (or rotate its code): prints the presenter URL, the code
                                          # and the QR link (t.me/<bot>?start=demo-<code>)
    python -m Pukaar.scripts.demo reset   # erase every demo person and demo alert now

Make: `make demo-open`, `make demo-reset` (the deployed stack of STAGE; refused on prod unless PUKAAR_LIVE_DEMO is on).
"""

from __future__ import annotations

import sys

from Pukaar.services import demo
from Pukaar.store.repo import get_repo

WHO = "cli"


def main(cmd: str = "open") -> None:
    repo = get_repo()
    if cmd == "open":
        try:
            s = demo.open_session(repo, WHO, "officer")
        except demo.DemoError as exc:
            raise SystemExit(exc.message_en) from None
        st = demo.status(repo, show_code=True)
        print(f"Presenter screen: {demo.presenter_url()}  (sign in as an officer)")
        print(f"Join code:        {s['code']}  (expires {s['code_expires_at']}, {demo.CODE_TTL_SECONDS // 60} min)")
        print(f"QR link:          {demo.join_link(str(s['code']))}")
        print(f"Joined so far:    {st['joined']} of {demo.MAX_PEOPLE}")
    elif cmd == "reset":
        erased = demo.reset(repo, WHO, "officer")
        print(f"Demo reset: {erased['people']} demo people and {erased['alerts']} demo alerts erased; the code no "
              "longer works. Run `make demo-open` for a new one.")
    else:
        raise SystemExit("usage: python -m Pukaar.scripts.demo open|reset")


if __name__ == "__main__":
    main(*sys.argv[1:2])
