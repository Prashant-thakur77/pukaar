"""Report-abuse protection: who sent a report (as salted hashes), rate limits, and independence.

The report page is public and anonymous, and GPS comes from the client. Without this, one script
could post two "people trapped" reports 300 m apart, auto-verify them against each other and raise
a village to Warning on the public site. Three defences, all in code:

1. Source, never raw. The API hashes the client IP, its network range (/24 for IPv4, /64 for IPv6)
   and the random device and session ids the report page keeps, each with HMAC-SHA256 under a salt
   kept in SSM (/pukaar/report_ip_salt). No raw IP is ever stored or logged. If the salt cannot be
   read, the hashes are left empty: the source is "unknown", which can never corroborate anything
   (fail closed), and ReportSaltMissing is counted.

2. Rate limits that hold, never drop. Two fixed-window counters in DynamoDB with a TTL: per source
   (salted IP hash) and per village. A report over either limit is still stored, shown to officers
   and on the villager's tracking page, but held: it is never auto-verified, never corroborates
   another report, never reaches a model, and counts towards a level only once an officer verifies
   it. ReportSurge is counted (alarmed) and the report carries a flag officers see.

3. Independence before corroboration. Two reports verify each other only if they come from a
   different device and session, not the same IP or network range, and both GPS fixes are plausible
   (inside the village radius, not 0,0, not the village's published centre copied from the public API).
   When a partner is rejected the report says why ("corroboration_rejected:same_network"), so an
   officer can verify it by hand. Shared mobile networks (carrier-grade NAT) can put two genuine
   villagers on one range: their reports wait for an officer instead of auto-verifying, the safe
   direction.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
from dataclasses import dataclass
from datetime import datetime

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.log import get_logger, log, metric
from Pukaar.store.models import Report, ReportSource, Village
from Pukaar.store.repo import Repo

_LOG = get_logger("report_guard")
SALT_NAME = "report_ip_salt"
HASH_CHARS = 16  # 64 bits of HMAC: enough to tell sources apart, too short to be an identifier elsewhere
CENTRE_COPY_M = 10  # a fix this close to the published village point is treated as copied, not measured
MAX_CLIENT_ID = 128

HOLD_SOURCE = "source_rate_limit"
HOLD_VILLAGE = "village_surge"
# Flags an officer sees on a report (frontend lib/humanize.ts labels them).
FLAG_SAME_SOURCE = "same_source"  # another recent report in this village came from the same source
FLAG_SOURCE_FLOOD = "source_flood"  # this source went over its rate limit
FLAG_SURGE = "report_surge"  # the village went over its rate limit
FLAG_SOURCE_UNKNOWN = "source_unknown"


# -- source ---------------------------------------------------------------------------------
def client_ip(headers, fallback: str | None) -> str | None:
    """The caller's IP as API Gateway saw it. The Lambda Web Adapter puts the request context in
    x-amzn-request-context (it replaces any copy a client sent); X-Forwarded-For's last entry is
    the one API Gateway appended. `fallback` is the socket peer, used in local mode only: on AWS
    the peer is the adapter itself (127.0.0.1), which would make every villager one source."""
    raw = headers.get("x-amzn-request-context")
    if raw:
        try:
            ctx = json.loads(raw)
            ip = (ctx.get("http") or {}).get("sourceIp") or (ctx.get("identity") or {}).get("sourceIp")
            if ip:
                return str(ip)
        except (ValueError, AttributeError):
            pass
    if get_settings().is_local:
        return fallback
    fwd = headers.get("x-forwarded-for", "")
    return (fwd.split(",")[-1].strip() or None) if fwd else None


def network_of(ip: str | None) -> str | None:
    """The /24 of an IPv4 address or the /64 of an IPv6 one; None if it is not an address."""
    if not ip:
        return None
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return None
    prefix = 24 if addr.version == 4 else 64
    return str(ipaddress.ip_network(f"{addr}/{prefix}", strict=False))


def _salt() -> bytes | None:
    from Pukaar.core.secrets import get_secret

    value = get_secret(SALT_NAME, generate_locally=True)
    return value.encode("utf-8") if value else None


def _h(salt: bytes, kind: str, value: str | None) -> str | None:
    value = (value or "").strip()[:MAX_CLIENT_ID]
    if not value:
        return None
    return hmac.new(salt, f"{kind}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()[:HASH_CHARS]


def make_source(ip: str | None, device_id: str | None, session_id: str | None) -> ReportSource:
    salt = _salt()
    if salt is None:
        metric("ReportSaltMissing", 1)
        log(_LOG, "report salt unavailable: source left unknown", 40)
        return ReportSource()
    return ReportSource(ip=_h(salt, "ip", ip), net=_h(salt, "net", network_of(ip)),
                        device=_h(salt, "device", device_id), session=_h(salt, "session", session_id))


# -- rate limits ------------------------------------------------------------------------------
@dataclass
class RateResult:
    hold_reason: str | None
    flags: list[str]
    source_count: int | None
    village_count: int


def _window(now: datetime, minutes: int) -> str:
    epoch = int(now.timestamp())
    start = epoch - epoch % (minutes * 60)
    return clock.iso(datetime.fromtimestamp(start, tz=now.tzinfo))


def check_rate(repo: Repo, village_id: str, source: ReportSource) -> RateResult:
    """Count this report against its source and its village. Never raises: a counter that cannot be
    written leaves the report unheld (the other defences still apply) and is logged."""
    s = get_settings()
    window = _window(clock.now(), s.report_window_minutes)
    flags: list[str] = []
    hold: str | None = None
    src_n: int | None = None
    village_n = 0
    try:
        village_n = repo.bump_rate("village", village_id, window)
        if source.ip:
            src_n = repo.bump_rate("src", source.ip, window)
    except Exception as exc:
        log(_LOG, "rate counter failed", 40, village_id=village_id, error=type(exc).__name__)
        return RateResult(None, [], None, 0)
    if src_n is not None and src_n > s.report_limit_per_source:
        hold = HOLD_SOURCE
        flags.append(FLAG_SOURCE_FLOOD)
        metric("ReportSurge", 1, Kind="source")
    if village_n > s.report_limit_per_village:
        hold = hold or HOLD_VILLAGE
        flags.append(FLAG_SURGE)
        metric("ReportSurge", 1, Kind="village", Village=village_id)
    if hold:
        log(_LOG, "report held: over rate limit", 30, village_id=village_id, reason=hold,
            source_count=src_n, village_count=village_n)
    return RateResult(hold, flags, src_n, village_n)


# -- same source, independence, plausibility -------------------------------------------------
def same_source(a: ReportSource | None, b: ReportSource | None) -> bool:
    """True when two reports share a known IP, network range or device."""
    if a is None or b is None:
        return False
    return any(x is not None and x == y for x, y in ((a.ip, b.ip), (a.net, b.net), (a.device, b.device)))


def not_independent(a: Report, b: Report) -> str | None:
    """Why two reports cannot corroborate each other, or None when they are independent."""
    sa, sb = a.source, b.source
    if sa is None or sb is None or not sa.ip or not sb.ip:
        return "source_unknown"
    if sa.ip == sb.ip:
        return "same_ip"
    if sa.net and sa.net == sb.net:
        return "same_network"
    if not sa.device or not sb.device:
        return "device_unknown"
    if sa.device == sb.device:
        return "same_device"
    if not sa.session or not sb.session:
        return "session_unknown"
    if sa.session == sb.session:
        return "same_session"
    return None


def implausible_gps(r: Report, v: Village, radius_m: float) -> str | None:
    """Why a report's fix cannot support auto-verification, or None when it is plausible."""
    from Pukaar.services.reports import distance_m

    if r.lat is None or r.lon is None:
        return "no_gps"
    if abs(r.lat) < 1e-6 and abs(r.lon) < 1e-6:
        return "null_island"
    d = distance_m(r.lat, r.lon, v.lat, v.lon)
    if d > radius_m:
        return "outside_village"
    if d < CENTRE_COPY_M:
        return "published_centre"
    return None
