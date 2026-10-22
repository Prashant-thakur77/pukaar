"""The scheduled canary: is the public face of Pukaar up, as a villager or an aggregator sees it?

EventBridge Scheduler runs it every 15 minutes (infra/template.yaml, CanarySchedule). It fetches, from
outside the app, exactly what the public fetches:

    GET <api>/health             200, JSON {"status": "ok", ...}
    GET <api>/public/overview    200, JSON with villages (each with a level and a data status) and
                                 counters.forecast_checks_24h above 0 (the sweep is storing forecasts)
    GET <api>/cap/alerts.atom    200, an Atom feed (SACHET and other CAP aggregators read it)
    GET <web>/                   200, the web app's index.html

Each check is tried twice, 5 seconds apart, so one dropped packet does not page anyone. The result goes
to CloudWatch with PutMetricData (namespace Pukaar; the function may write nothing else): CanaryFailed 0
when every check passed, 1 when any failed, plus CanaryFailed 1 with dimension Check for each failed
check. The pukaar-<stage>-canary-failed alarm fires on a failure, and also when no result arrives at all.

Standard library and boto3 only: it imports nothing from the app, so a broken app module cannot make the
canary pass. No CloudWatch Synthetics: that bills per canary run; this costs one Lambda invocation.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

NAMESPACE = "Pukaar"
TIMEOUT_SECONDS = 10.0
RETRY_SECONDS = 5.0
LEVELS = {"normal", "watch", "warning", "critical"}
DATA_STATUSES = {"ok", "stale", "unavailable"}
USER_AGENT = "pukaar-canary/1"


@dataclass
class Response:
    status: int
    body: bytes
    content_type: str


class CheckFailed(Exception):
    pass


def fetch(url: str) -> Response:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as r:  # noqa: S310 (https URLs from the stack)
            return Response(r.status, r.read(2_000_000), r.headers.get("Content-Type", ""))
    except urllib.error.HTTPError as exc:
        return Response(exc.code, exc.read(2000) if exc.fp else b"", exc.headers.get("Content-Type", "") if exc.headers else "")


def _ok(r: Response, what: str) -> None:
    if r.status != 200:
        raise CheckFailed(f"{what}: HTTP {r.status}")


def _json(r: Response, what: str) -> Any:
    try:
        return json.loads(r.body)
    except ValueError:
        raise CheckFailed(f"{what}: not JSON") from None


def check_health(r: Response) -> None:
    _ok(r, "/health")
    data = _json(r, "/health")
    if not isinstance(data, dict) or data.get("status") != "ok":
        raise CheckFailed(f"/health: status {data.get('status') if isinstance(data, dict) else data!r}")


def check_overview(r: Response) -> None:
    _ok(r, "/public/overview")
    data = _json(r, "/public/overview")
    villages = data.get("villages") if isinstance(data, dict) else None
    if not isinstance(villages, list) or not villages:
        raise CheckFailed("/public/overview: no villages")
    for v in villages:
        if not isinstance(v, dict) or v.get("level") not in LEVELS or v.get("data_status") not in DATA_STATUSES:
            raise CheckFailed(f"/public/overview: village {v.get('id') if isinstance(v, dict) else v!r} malformed")
    checks = (data.get("counters") or {}).get("forecast_checks_24h")
    if not isinstance(checks, int) or checks <= 0:
        raise CheckFailed(f"/public/overview: forecast_checks_24h is {checks!r} (is the sweep storing forecasts?)")


def check_cap(r: Response) -> None:
    _ok(r, "/cap/alerts.atom")
    head = r.body[:4000].decode("utf-8", "replace")
    if "<feed" not in head or "http://www.w3.org/2005/Atom" not in head:
        raise CheckFailed("/cap/alerts.atom: not an Atom feed")


def check_web(r: Response) -> None:
    _ok(r, "index.html")
    text = r.body.decode("utf-8", "replace")
    if '<div id="root">' not in text or "<script" not in text:
        raise CheckFailed("index.html: not the Pukaar web app")


def checks(api: str, web: str) -> list[tuple[str, str, Callable[[Response], None]]]:
    api, web = api.rstrip("/"), web.rstrip("/")
    return [
        ("health", f"{api}/health", check_health),
        ("overview", f"{api}/public/overview", check_overview),
        ("cap", f"{api}/cap/alerts.atom", check_cap),
        ("web", f"{web}/", check_web),
    ]


def run(api: str, web: str, *, get: Callable[[str], Response] = fetch,
        sleep: Callable[[float], None] = time.sleep) -> dict[str, str]:
    """{check: "ok" | the reason it failed}. Never raises."""
    out: dict[str, str] = {}
    for name, url, check in checks(api, web):
        reason = "ok"
        for attempt in range(2):
            try:
                check(get(url))
                reason = "ok"
                break
            except CheckFailed as exc:
                reason = str(exc)
            except Exception as exc:  # timeouts, DNS, TLS
                reason = f"{url}: {type(exc).__name__}: {str(exc)[:200]}"
            if attempt == 0:
                sleep(RETRY_SECONDS)
        out[name] = reason
    return out


def metric_data(results: dict[str, str]) -> list[dict[str, Any]]:
    failed = [n for n, r in results.items() if r != "ok"]
    data: list[dict[str, Any]] = [{"MetricName": "CanaryFailed", "Value": 1.0 if failed else 0.0, "Unit": "Count"}]
    data += [{"MetricName": "CanaryFailed", "Value": 1.0, "Unit": "Count",
              "Dimensions": [{"Name": "Check", "Value": n}]} for n in failed]
    return data


def handler(event: dict | None = None, context: Any = None, *, get: Callable[[str], Response] = fetch,
            cloudwatch: Any = None, sleep: Callable[[float], None] = time.sleep) -> dict:
    api = os.environ.get("PUKAAR_CANARY_API_URL", "").strip()
    web = os.environ.get("PUKAAR_WEB_URL", "").strip()
    results = run(api, web, get=get, sleep=sleep) if api and web else {"config": "PUKAAR_CANARY_API_URL or "
                                                                                 "PUKAAR_WEB_URL is not set"}
    if cloudwatch is None:
        import boto3

        cloudwatch = boto3.client("cloudwatch")
    cloudwatch.put_metric_data(Namespace=NAMESPACE, MetricData=metric_data(results))
    ok = all(r == "ok" for r in results.values())
    print(json.dumps({"level": "INFO" if ok else "ERROR", "logger": "Pukaar.canary",
                      "msg": "canary passed" if ok else "canary failed", "results": results}), flush=True)
    return {"ok": ok, "results": results}
