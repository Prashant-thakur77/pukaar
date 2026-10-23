"""SACHET in: NDMA's public CAP alerts for Himachal Pradesh, read as one more official source.

SACHET (NDMA's CAP platform, built by C-DOT) publishes a public RSS feed per state. Each item links to one
CAP 1.2 message (FetchXMLFile?identifier=...). Pukaar reads the Himachal feed
(Settings.sachet_rss_url, default https://sachet.ndma.gov.in/cap_public_website/rss/rss_himachal.xml,
seen live on 23 October 2026), fetches the newest few CAP messages, and asks of each one: is it in force
now, and does it cover this village?

A message covers a village when one of these holds:
  - a <polygon> or <circle> of its <area> contains the village point;
  - a geocode "LGD District Code" equals the village's district code;
  - its areaDesc or headline names the village's district (English or Hindi) or the village itself.
A message that names none of these is kept as regional context for the state and implies no level.

What it implies: CAP severity Extreme -> critical, Severe -> warning, Moderate -> watch, Minor -> nothing,
and only for a flood-related event (heavy rain, flood, cloudburst, landslide; English or Hindi words). A
thunderstorm or "light to moderate rain" message is shown and implies nothing. Like every official source,
the item is evidence for the officer; risk_rules raises a level on it only when
PUKAAR_OFFICIAL_RAISES_LEVEL is on, and never lowers one. It never sounds a siren (Cedar
"external-cap-never-sounds").

Exercise, Test and Draft messages are ignored, and so is any message a Cancel in the same feed refers to.
The RSS is cached for 10 minutes and each CAP message for a day (services/fetch_cache.py), so the sweep
asks SACHET at most once per 10 minutes whatever the number of villages. Every failure is "unavailable",
never "normal". The polygon file SACHET links to (FetchPolygonXMLFile) refused anonymous requests (403)
when checked, so polygons are read only when a message carries them inline.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.log import get_logger, log
from Pukaar.services import fetch_cache
from Pukaar.store.models import Village, level_rank

_LOG = get_logger("sachet")

SOURCE = "sachet"
NAME = "SACHET (NDMA) CAP alerts for Himachal Pradesh"
DEFAULT_RSS = "https://sachet.ndma.gov.in/cap_public_website/rss/rss_himachal.xml"
CAP_NS = "urn:oasis:names:tc:emergency:cap:1.2"
RSS_CACHE_S, CAP_CACHE_S, FAILURE_CACHE_S = 600, 86400, 300
MAX_BYTES = 1_000_000
USER_AGENT = "Pukaar flood early warning (reads the public SACHET feed; contact via the project README)"
# Without an <expires>, a message counts for this long after it was sent.
DEFAULT_LIFETIME = timedelta(hours=24)

SEVERITY_LEVEL = {"extreme": "critical", "severe": "warning", "moderate": "watch"}
# Heavy rain, floods, cloudbursts and landslides; "light to moderate rain" is not a flood source.
FLOOD_WORDS = re.compile(
    r"heavy rain|heavy to very heavy|very heavy|extremely heavy|heavy rainfall|flood|cloud ?burst|landslide|"
    r"land slide|inundat|"
    r"भारी बारिश|भारी वर्षा|अति भारी|बहुत भारी|बाढ़|बाढ|बादल फट|भूस्खलन|जलभराव",
    re.IGNORECASE,
)
LGD_DISTRICT = "lgd district code"


class SachetError(ValueError):
    """The feed or a message was not what we expect: read as unavailable, never as "no alert"."""


# -- parsing -------------------------------------------------------------------------------------
def _safe_xml(body: bytes | str) -> ET.Element:
    raw = body.encode("utf-8") if isinstance(body, str) else body
    if len(raw) > MAX_BYTES:
        raise SachetError("response too large")
    head = raw[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in raw.upper():
        raise SachetError("DTDs and entities are refused")
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise SachetError(f"not XML: {exc}") from None


def _when(text: str | None) -> datetime | None:
    if not text:
        return None
    t = text.strip()
    try:
        dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(t)
        except (TypeError, ValueError):
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_rss(body: bytes | str) -> list[dict[str, Any]]:
    """The items of a SACHET RSS feed, newest first: guid, link (the CAP file), title, author, published."""
    root = _safe_xml(body)
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise SachetError("expected an RSS 2.0 <rss><channel>")
    items = []
    for it in channel.findall("item"):
        link = (it.findtext("link") or "").strip()
        guid = (it.findtext("guid") or "").strip() or link
        if not link or not guid:
            continue
        published = _when(it.findtext("pubDate"))
        items.append({"guid": guid, "link": link, "title": (it.findtext("title") or "").strip()[:500],
                      "author": (it.findtext("author") or "").strip()[:120],
                      "published": clock.iso(published) if published else None})
    items.sort(key=lambda i: i["published"] or "", reverse=True)
    return items


def _t(el: ET.Element, tag: str) -> str:
    return (el.findtext(f"{{{CAP_NS}}}{tag}") or "").strip()


def _points(text: str) -> list[tuple[float, float]]:
    out = []
    for pair in text.split():
        try:
            lat, lon = pair.split(",")[:2]
            out.append((float(lat), float(lon)))
        except ValueError:
            continue
    return out


def parse_cap(body: bytes | str) -> dict[str, Any]:
    """One CAP 1.2 message: the fields Pukaar reads. Raises SachetError on another document."""
    root = _safe_xml(body)
    if root.tag != f"{{{CAP_NS}}}alert":
        raise SachetError("expected a CAP 1.2 <alert>")
    infos = []
    for info in root.findall(f"{{{CAP_NS}}}info"):
        areas = []
        for area in info.findall(f"{{{CAP_NS}}}area"):
            geocodes: dict[str, list[str]] = {}
            for g in area.findall(f"{{{CAP_NS}}}geocode"):
                geocodes.setdefault(_t(g, "valueName").lower(), []).append(_t(g, "value"))
            circles = []
            for c in area.findall(f"{{{CAP_NS}}}circle"):
                parts = (c.text or "").split()
                pts = _points(parts[0]) if parts else []
                try:
                    radius = float(parts[1]) if len(parts) > 1 else 0.0
                except ValueError:
                    radius = 0.0
                if pts:
                    circles.append((pts[0][0], pts[0][1], radius))
            areas.append({"desc": _t(area, "areaDesc"), "geocodes": geocodes, "circles": circles,
                          "polygons": [p for p in (_points(x.text or "") for x in area.findall(f"{{{CAP_NS}}}polygon"))
                                       if len(p) >= 4]})
        infos.append({"language": _t(info, "language"), "event": _t(info, "event"),
                      "urgency": _t(info, "urgency"), "severity": _t(info, "severity"),
                      "certainty": _t(info, "certainty"), "effective": _t(info, "effective"),
                      "onset": _t(info, "onset"), "expires": _t(info, "expires"), "headline": _t(info, "headline"),
                      "description": _t(info, "description"), "instruction": _t(info, "instruction"),
                      "areas": areas})
    if not infos:
        raise SachetError("a CAP message without an <info>")
    return {"identifier": _t(root, "identifier"), "sender": _t(root, "sender"), "sent": _t(root, "sent"),
            "status": _t(root, "status"), "msg_type": _t(root, "msgType"), "references": _t(root, "references"),
            "infos": infos}


# -- matching ------------------------------------------------------------------------------------
def _in_polygon(lat: float, lon: float, poly: list[tuple[float, float]]) -> bool:
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        (yi, xi), (yj, xj) = poly[i], poly[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math

    dy = (lat1 - lat2) * 111.2
    dx = (lon1 - lon2) * 111.2 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def _names(village: Village) -> list[str]:
    from Pukaar.services.cap import district_hi

    names = [village.district, district_hi(village), village.name, village.name_hi]
    return [n for n in dict.fromkeys(n.strip() for n in names if n and n.strip())]


def _mentions(text: str, name: str) -> bool:
    if not text or not name:
        return False
    if name.isascii():
        return re.search(rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])", text, re.IGNORECASE) is not None
    return name in text


def how_it_covers(msg: dict[str, Any], village: Village) -> str | None:
    """Why this message covers the village ("polygon", "circle", "LGD district code", "names Mandi"), or None."""
    from Pukaar.services.cap import lgd_codes

    district_code = lgd_codes(village)[0]
    names = _names(village)
    areas = [a for info in msg["infos"] for a in info["areas"]]
    if any(_in_polygon(village.lat, village.lon, p) for a in areas for p in a["polygons"]):
        return "polygon"
    if any(_km(village.lat, village.lon, la, lo) <= r for a in areas for la, lo, r in a["circles"]):
        return "circle"
    if district_code and any(district_code in a["geocodes"].get(LGD_DISTRICT, []) for a in areas):
        return "LGD district code"
    texts = [t for info in msg["infos"] for t in (info["headline"], info["description"])] + [a["desc"] for a in areas]
    for name in names:
        if any(_mentions(t, name) for t in texts):
            return f"names {name}"
    return None


def in_force(msg: dict[str, Any], now: datetime, published: str | None = None) -> bool:
    if msg["status"].lower() != "actual" or msg["msg_type"].lower() == "cancel":
        return False
    expiries = [e for e in (_when(i["expires"]) for i in msg["infos"]) if e is not None]
    if expiries:
        return max(expiries) > now
    sent = _when(msg["sent"]) or _when(published)
    return sent is not None and sent + DEFAULT_LIFETIME > now


def cancelled_ids(messages: list[dict[str, Any]]) -> set[str]:
    """Identifiers a Cancel in the feed refers to ("sender,identifier,sent" triples)."""
    out: set[str] = set()
    for m in messages:
        if m["msg_type"].lower() == "cancel":
            for ref in m["references"].split():
                parts = ref.split(",")
                if len(parts) >= 2:
                    out.add(parts[1])
    return out


def implies(msg: dict[str, Any]) -> str | None:
    """The level a covering message implies: from severity, flood-related events only."""
    best: str | None = None
    for info in msg["infos"]:
        text = " ".join([info["event"], info["headline"], info["description"]])
        if not FLOOD_WORDS.search(text):
            continue
        lvl = SEVERITY_LEVEL.get(info["severity"].lower())
        if lvl and (best is None or level_rank(lvl) > level_rank(best)):
            best = lvl
    return best


def _headline(msg: dict[str, Any], hindi: bool) -> str:
    for info in msg["infos"]:
        lang = info["language"].lower()
        if (lang.startswith("hi") if hindi else lang.startswith("en")) and info["headline"]:
            return info["headline"][:300]
    return msg["infos"][0]["headline"][:300] if not hindi else ""


def summary(msg: dict[str, Any], link: str = "", how: str | None = None) -> dict[str, Any]:
    first = msg["infos"][0]
    return {"identifier": msg["identifier"], "sender": msg["sender"], "sent": msg["sent"],
            "event": first["event"], "severity": first["severity"], "urgency": first["urgency"],
            "expires": max((i["expires"] for i in msg["infos"] if i["expires"]), default=None),
            "headline_en": _headline(msg, False), "headline_hi": _headline(msg, True),
            "area": first["areas"][0]["desc"] if first["areas"] else "", "link": link, "covers": how,
            "implies": implies(msg) if how else None}


def item_for(messages: list[tuple[dict[str, Any], str, str | None]], village: Village, now: datetime,
             fetched_at: str | None = None) -> dict[str, Any]:
    """The official item for one village from the parsed feed: (message, link, published) triples."""
    parsed = [m for m, _, _ in messages]
    gone = cancelled_ids(parsed)
    matched, regional = [], []
    for msg, link, published in messages:
        if msg["identifier"] in gone or not in_force(msg, now, published):
            continue
        how = how_it_covers(msg, village)
        (matched if how else regional).append(summary(msg, link, how))
    levels = [m["implies"] for m in matched if m["implies"]]
    level = max(levels, key=level_rank) if levels else "normal"
    detail = (f"{len(matched)} SACHET alert(s) in force for {village.district} or this village; "
              f"{len(regional)} elsewhere in Himachal Pradesh")
    if matched and not levels:
        detail += " (none flood-related, so no level implied)"
    return {"source": SOURCE, "name": NAME, "status": "ok", "level": level, "detail": detail,
            "matched": matched[:5], "regional": regional[:5], "regional_count": len(regional),
            "fetched_at": fetched_at, "url": get_settings().sachet_rss_url}


# -- fetching ------------------------------------------------------------------------------------
def _get(client: Any, url: str) -> bytes:
    r = client.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/xml, text/xml, */*"})
    r.raise_for_status()
    body = getattr(r, "content", None)
    if body is None:
        body = getattr(r, "text", "")
    return body.encode("utf-8") if isinstance(body, str) else bytes(body)


def fetch_feed(client: Any) -> dict[str, Any]:
    """The RSS items and their CAP messages (cached; one fetch per 10 minutes for every village)."""
    s = get_settings()

    def _rss() -> dict[str, Any]:
        try:
            items = parse_rss(_get(client, s.sachet_rss_url))
        except Exception as exc:
            log(_LOG, "sachet rss failed", 30, error=f"{type(exc).__name__}: {exc}"[:200])
            return {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}"[:200]}
        return {"status": "ok", "items": items[: s.sachet_max_items], "fetched_at": clock.iso(clock.now())}

    feed = fetch_cache.get_or_fetch(f"official:sachet:rss:{s.sachet_rss_url}", RSS_CACHE_S, _rss,
                                    failure_ttl_seconds=FAILURE_CACHE_S)
    if feed.get("status") != "ok":
        return feed
    messages, failed = [], 0
    for it in feed["items"]:
        def _cap(it=it) -> dict[str, Any]:
            try:
                return {"status": "ok", "message": parse_cap(_get(client, it["link"]))}
            except Exception as exc:
                return {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}"[:200]}

        got = fetch_cache.get_or_fetch(f"official:sachet:cap:{it['guid']}", CAP_CACHE_S, _cap,
                                       failure_ttl_seconds=FAILURE_CACHE_S)
        if got.get("status") == "ok":
            messages.append((got["message"], it["link"], it.get("published")))
        else:
            failed += 1
    if feed["items"] and not messages:
        return {"status": "unavailable", "error": f"none of the {failed} CAP messages could be read"}
    return {"status": "ok", "messages": messages, "failed": failed, "fetched_at": feed.get("fetched_at")}


def item(client: Any, village: Village, now: datetime | None = None) -> dict[str, Any]:
    """The SACHET item for a village; "off" when switched off, "unavailable" on any failure."""
    s = get_settings()
    if not s.sachet_enabled:
        return {"source": SOURCE, "name": NAME, "status": "off", "level": None,
                "detail": "PUKAAR_SACHET=true to read the SACHET feed"}
    feed = fetch_feed(client)
    if feed.get("status") != "ok":
        return {"source": SOURCE, "name": NAME, "status": "unavailable", "level": None,
                "error": str(feed.get("error", "unavailable"))[:200], "fetched_at": clock.iso(clock.now())}
    out = item_for([tuple(m) for m in feed["messages"]], village, now or clock.now(), feed.get("fetched_at"))
    if feed.get("failed"):
        out["detail"] += f"; {feed['failed']} message(s) could not be read"
    return out
