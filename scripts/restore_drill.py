#!/usr/bin/env python3
"""Restore drill: prove the table can be brought back from point-in-time recovery (docs/RUNBOOK.md).

    python scripts/restore_drill.py [--stage dev] [--at 2026-10-22T10:00:00Z] [--keep]

1. Restores pukaar-<stage> as it was at --at (default: the latest restorable time) into a scratch table
   named pukaar-<stage>-restore-drill-<UTC stamp>. Nothing is written to the live table; it is only read.
2. Counts the items under each key prefix (VILLAGE#, ALERT#, ...) in both tables: the scans read the
   partition key only, and only the counts are printed; no item's contents are read out.
3. Deletes the scratch table (unless --keep), even when a step failed.

PASS when every key prefix the live table has is in the restored copy too, and each count is within
--tolerance (default 10 %) of the live one. Exact equality is not expected: the live table has written
new items since the restore point, and TTL has removed others. Exit 0 on PASS, 1 on FAIL.

Cost: a restore is billed per GB restored (cents for this table), and the two scans read the table twice
on demand. The scratch table is on-demand and lives only for the drill.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone

PREFIX = "pukaar-{stage}-restore-drill-"


def scratch_name(stage: str, now: datetime | None = None) -> str:
    return PREFIX.format(stage=stage) + (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")


def is_scratch(name: str, stage: str) -> bool:
    return name.startswith(PREFIX.format(stage=stage))


def count_by_prefix(client, table: str) -> dict[str, int]:
    """Items per key prefix (the part of pk before the first '#', plus '#'). Reads the key only."""
    counts: dict[str, int] = {}
    kwargs = {"TableName": table, "ProjectionExpression": "pk"}
    while True:
        page = client.scan(**kwargs)
        for item in page.get("Items", []):
            pk = item["pk"]["S"]
            key = pk.split("#", 1)[0] + "#" if "#" in pk else pk
            counts[key] = counts.get(key, 0) + 1
        if "LastEvaluatedKey" not in page:
            return counts
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def compare(live: dict[str, int], restored: dict[str, int], tolerance: float) -> tuple[bool, list[str]]:
    lines, ok = [], True
    for key in sorted(set(live) | set(restored)):
        a, b = live.get(key, 0), restored.get(key, 0)
        good = b > 0 if a > 0 else True
        if good and a:
            good = abs(a - b) <= max(2, tolerance * a)
        ok &= good
        lines.append(f"  {key:<14} live {a:>7}  restored {b:>7}  {'ok' if good else 'DIFFERS'}")
    lt, rt = sum(live.values()), sum(restored.values())
    lines.append(f"  {'total':<14} live {lt:>7}  restored {rt:>7}")
    return ok and rt > 0, lines


def wait_active(client, table: str, timeout_s: int, poll_s: float = 20.0) -> None:
    start = time.monotonic()
    while True:
        status = client.describe_table(TableName=table)["Table"]["TableStatus"]
        if status == "ACTIVE":
            return
        if time.monotonic() - start > timeout_s:
            raise TimeoutError(f"{table} still {status} after {timeout_s} s")
        print(f"  {table}: {status} ({int(time.monotonic() - start)} s)", flush=True)
        time.sleep(poll_s)


def drill(client, stage: str, at: datetime | None, *, keep: bool = False, tolerance: float = 0.1,
          timeout_s: int = 3600, poll_s: float = 20.0) -> bool:
    source = f"pukaar-{stage}"
    target = scratch_name(stage)
    assert is_scratch(target, stage) and target != source  # never anything but a scratch table
    pitr = client.describe_continuous_backups(TableName=source)["ContinuousBackupsDescription"]
    desc = pitr.get("PointInTimeRecoveryDescription", {})
    if desc.get("PointInTimeRecoveryStatus") != "ENABLED":
        print(f"FAIL: point-in-time recovery is not enabled on {source}")
        return False
    print(f"{source}: restorable {desc['EarliestRestorableDateTime']} to {desc['LatestRestorableDateTime']}")
    args = {"SourceTableName": source, "TargetTableName": target, "BillingModeOverride": "PAY_PER_REQUEST"}
    if at is None:
        args["UseLatestRestorableTime"] = True
    else:
        args["RestoreDateTime"] = at
    started = time.monotonic()
    print(f"restoring {source} ({'latest' if at is None else at.isoformat()}) into {target}", flush=True)
    client.restore_table_to_point_in_time(**args)
    try:
        wait_active(client, target, timeout_s, poll_s)
        took = int(time.monotonic() - started)
        print(f"restored in {took} s; counting items by key prefix", flush=True)
        live, restored = count_by_prefix(client, source), count_by_prefix(client, target)
        ok, lines = compare(live, restored, tolerance)
        print("\n".join(lines))
        print(f"{'PASS' if ok else 'FAIL'}: restore of {source} took {took} s")
        return ok
    finally:
        if keep:
            print(f"kept {target}: delete it yourself (aws dynamodb delete-table --table-name {target})")
        else:
            try:
                wait_active(client, target, timeout_s, poll_s)
            except Exception:
                pass
            client.delete_table(TableName=target)
            print(f"deleted {target}")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--stage", default=os.environ.get("STAGE", "dev"))
    p.add_argument("--region", default=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"))
    p.add_argument("--at", help="restore point, ISO 8601 in UTC (default: the latest restorable time)")
    p.add_argument("--keep", action="store_true", help="keep the scratch table for a look (delete it after)")
    p.add_argument("--tolerance", type=float, default=0.1)
    a = p.parse_args(argv)
    import boto3

    at = datetime.fromisoformat(a.at.replace("Z", "+00:00")) if a.at else None
    client = boto3.client("dynamodb", region_name=a.region)
    return 0 if drill(client, a.stage, at, keep=a.keep, tolerance=a.tolerance) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
