"""Assign a staff account (officer, state operator, DDMA head) to districts: the district scope of
services/scope.py and policy/base.cedar ("staff-own-district", "ddma-head-own-district").

    python -m Pukaar.scripts.staff <username> "Mandi,Hamirpur"   # assign (replaces the list)
    python -m Pukaar.scripts.staff <username> ""                  # remove every district
    python -m Pukaar.scripts.staff <username>                     # show

The role itself is the account's Cognito group (officer, state_operator, ddma_head, pradhan; docs/DEPLOY.md).
An officer can also act where they are on the duty roster, or on a village whose officer list names them.
"""

from __future__ import annotations

import sys

from Pukaar.services import roster
from Pukaar.store.repo import get_repo


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    repo = get_repo()
    username = argv[0].strip()
    if len(argv) == 1:
        print(f"{username}: {', '.join(repo.get_staff_scope(username)) or '(no district)'}")
        return 0
    wanted = [d.strip() for d in argv[1].split(",") if d.strip()]
    known = set(roster.districts(repo))
    unknown = [d for d in wanted if d not in known]
    if unknown:
        print(f"unknown district(s): {', '.join(unknown)}; known: {', '.join(sorted(known))}", file=sys.stderr)
        return 2
    repo.put_staff_scope(username, wanted)
    print(f"{username}: {', '.join(wanted) or '(no district)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
