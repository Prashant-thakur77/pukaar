"""Virtual staff gauges from photos (the CrowdWater pattern, University of Zurich).

Set-up (once per spot, by an officer or the village's pradhan): a reference photo of a fixed
object by the khad (a big rock, a bridge pier, a wall), taken square to the stream, and a scale
drawn on it in the browser: two taps for the top and bottom of a known span, then the marks in
between, either CrowdWater-style relative classes ("-5" ... "+5") or heights in cm. The photo is
in S3 (staffgauges/<village>/<id>.<ext>) and the gauge in DynamoDB (VILLAGE#id / STAFFGAUGE#id).

Reading (any villager, no account): on the report page the villager compares the reference photo
and its scale with the water now and taps the mark closest to the water. The choice is stored on
the report as `staff_reading` together with the villager's own photo.

Confirmation (officers only): the console shows the reference and the new photo side by side with
the scale; the officer confirms the mark, adjusts it, or marks the photo unreadable. Every change
is audited (old -> new).

What a reading can do to the level (risk_rules.assess):
  - unconfirmed (the villager's mark only): shown in the evidence, never changes a level;
  - confirmed by an officer, at or above the gauge's configured watch/warning/critical mark: an
    observation that raises the village to that level, the same weight as an officer-verified
    report, fading over the same three hours. It counts as a source separate from other reports,
    so it corroborates a verified report from someone else (two sources agree: +1 level), but its
    own report never counts twice;
  - confirmed below every configured mark, or a gauge with no marks configured: evidence only.

A vision model reading the photo automatically waits for Bedrock model access; until then a
person reads every photo, and the UI says so.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any

from Pukaar.core import clock
from Pukaar.core.ids import new_id
from Pukaar.core.log import get_logger, log
from Pukaar.services import storage
from Pukaar.store.models import (
    AuditRow,
    Report,
    StaffGauge,
    StaffMark,
    StaffReading,
    Village,
)
from Pukaar.store.repo import Repo

_LOG = get_logger("staff_gauge")
MIN_MARKS = 2
MAX_MARKS = 41
MIN_SPAN = 0.05  # top and bottom taps at least 5% of the photo apart
MAX_GAUGES_PER_VILLAGE = 5
PHOTO_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
VISION_NOTE_EN = ("Read by a person: automatic reading of the photo by a vision model waits for Bedrock "
                  "model access.")
VISION_NOTE_HI = "फ़ोटो एक व्यक्ति पढ़ता है: मॉडल से अपने-आप पढ़ना Bedrock की अनुमति मिलने के बाद।"


class StaffGaugeError(ValueError):
    """A set-up or a reading the server will not store, with a reason in both languages."""

    def __init__(self, en: str, hi: str = "") -> None:
        super().__init__(en)
        self.en, self.hi = en, hi or en


def validate(g: StaffGauge) -> None:
    """Scale sanity: a real span, 2..41 marks with distinct increasing values, thresholds on marks."""
    dy, dx = g.scale_bottom.y - g.scale_top.y, g.scale_bottom.x - g.scale_top.x
    if (dx * dx + dy * dy) ** 0.5 < MIN_SPAN:
        raise StaffGaugeError("Tap the top and the bottom of the scale further apart.",
                              "पैमाने का ऊपर और नीचे वाला सिरा थोड़ा दूर-दूर चुनें।")
    if dy <= 0:
        raise StaffGaugeError("The top of the scale must be above its bottom in the photo.",
                              "पैमाने का ऊपरी सिरा फ़ोटो में नीचे वाले सिरे से ऊपर होना चाहिए।")
    if not MIN_MARKS <= len(g.marks) <= MAX_MARKS:
        raise StaffGaugeError(f"Use between {MIN_MARKS} and {MAX_MARKS} marks.",
                              f"{MIN_MARKS} से {MAX_MARKS} तक निशान रखें।")
    values = [m.value for m in g.marks]
    if len(set(values)) != len(values):
        raise StaffGaugeError("Two marks have the same value.", "दो निशानों का मान एक जैसा है।")
    labels = [m.label.strip() for m in g.marks]
    if len(set(labels)) != len(labels) or not all(labels):
        raise StaffGaugeError("Each mark needs its own label.", "हर निशान का अलग नाम होना चाहिए।")
    # Higher water is higher in the photo: a larger value must sit higher (smaller y).
    ordered = sorted(g.marks, key=lambda m: m.value)
    if any(b.y > a.y + 1e-6 for a, b in pairwise(ordered)):
        raise StaffGaugeError("Higher marks must be higher in the photo.", "ऊँचे निशान फ़ोटो में ऊपर होने चाहिए।")
    if g.unit == "cm" and any(m.height_cm is None for m in g.marks):
        raise StaffGaugeError("Give every mark a height in cm.", "हर निशान की ऊँचाई सेमी में दें।")
    set_values = set(values)
    chosen = [t for t in (g.watch_at, g.warning_at, g.critical_at) if t is not None]
    if any(t not in set_values for t in chosen):
        raise StaffGaugeError("A threshold must be one of the marks.", "सीमा किसी एक निशान पर होनी चाहिए।")
    if chosen != sorted(chosen) or len(set(chosen)) != len(chosen):
        raise StaffGaugeError("Thresholds must rise: watch, then warning, then critical.",
                              "सीमाएँ बढ़ते क्रम में हों: पहले Watch, फिर Warning, फिर Critical।")


def mark_for(g: StaffGauge, value: float) -> StaffMark:
    for m in g.marks:
        if abs(m.value - value) < 1e-9:
            return m
    raise StaffGaugeError("That mark is not on this gauge.", "यह निशान इस पैमाने पर नहीं है।")


def level_for(g: StaffGauge, value: float) -> str:
    """The level a mark means on this gauge: the highest configured threshold it reaches."""
    level = "normal"
    for name in ("watch", "warning", "critical"):
        at = getattr(g, f"{name}_at")
        if at is not None and value >= at:
            level = name
    return level


def view(g: StaffGauge) -> dict[str, Any]:
    out = g.model_dump(exclude={"photo_key"})
    out["photo_url"] = storage.url_for(g.photo_key)
    out["vision_note_en"], out["vision_note_hi"] = VISION_NOTE_EN, VISION_NOTE_HI
    return out


def active(repo: Repo, village_id: str) -> list[StaffGauge]:
    return [g for g in repo.list_staff_gauges(village_id) if g.active]


def _audit(repo: Repo, actor: str, role: str, action: str, resource: str, reason: str) -> None:
    repo.append_audit(AuditRow(at=clock.iso(clock.now()), id=new_id("aud"), actor=actor, role=role, action=action,
                               resource=resource, decision="allow", reason=reason[:500]))


def create(repo: Repo, village: Village, *, photo: tuple[bytes, str], fields: dict[str, Any], actor: str,
           role: str) -> StaffGauge:
    ctype = photo[1].split(";")[0].strip()
    if ctype not in PHOTO_TYPES:
        raise StaffGaugeError("The reference must be a JPEG, PNG or WebP photo.", "संदर्भ फ़ोटो JPEG, PNG या WebP हो।")
    if len(active(repo, village.id)) >= MAX_GAUGES_PER_VILLAGE:
        raise StaffGaugeError(f"A village can have at most {MAX_GAUGES_PER_VILLAGE} reference points.",
                              f"एक गाँव में ज़्यादा से ज़्यादा {MAX_GAUGES_PER_VILLAGE} संदर्भ स्थान।")
    gid = new_id("stg")
    now = clock.iso(clock.now())
    try:
        g = StaffGauge(id=gid, village_id=village.id, photo_key="pending", created_by=actor, created_at=now,
                       **{k: v for k, v in fields.items() if k in _EDITABLE})
    except ValueError as exc:
        raise StaffGaugeError(f"Invalid staff gauge: {str(exc)[:200]}", "पैमाने की जानकारी सही नहीं है।") from None
    validate(g)
    g.photo_key = storage.put_bytes(f"staffgauges/{village.id}/{gid}.{PHOTO_TYPES[ctype]}", photo[0], ctype)
    repo.put_staff_gauge(g)
    _audit(repo, actor, role, "staff_gauge_create", f"staffgauge:{village.id}:{gid}",
           f"'{g.name}': {len(g.marks)} marks {g.marks[0].label}..{g.marks[-1].label} ({g.unit}); "
           f"thresholds {_thresholds(g)}")
    log(_LOG, "staff gauge created", village_id=village.id, gauge_id=gid, marks=len(g.marks))
    return g


_EDITABLE = {"name", "name_hi", "where", "scale_top", "scale_bottom", "unit", "marks", "watch_at", "warning_at",
             "critical_at", "active"}


def _thresholds(g: StaffGauge) -> str:
    return ", ".join(f"{n} {getattr(g, n + '_at'):g}" if getattr(g, n + "_at") is not None else f"{n} -"
                     for n in ("watch", "warning", "critical"))


def update(repo: Repo, g: StaffGauge, fields: dict[str, Any], *, actor: str, role: str) -> StaffGauge:
    changes = {k: v for k, v in fields.items() if k in _EDITABLE}
    data = {**g.model_dump(), **changes, "updated_by": actor, "updated_at": clock.iso(clock.now())}
    try:
        new = StaffGauge.model_validate(data)
    except ValueError as exc:
        raise StaffGaugeError(f"Invalid staff gauge: {str(exc)[:200]}", "पैमाने की जानकारी सही नहीं है।") from None
    validate(new)
    repo.put_staff_gauge(new)
    what = []
    if _thresholds(g) != _thresholds(new):
        what.append(f"thresholds {_thresholds(g)} -> {_thresholds(new)}")
    if g.active != new.active:
        what.append("retired" if not new.active else "re-activated")
    if [m.model_dump() for m in g.marks] != [m.model_dump() for m in new.marks]:
        what.append(f"scale redrawn ({len(new.marks)} marks)")
    if (g.name, g.name_hi, g.where) != (new.name, new.name_hi, new.where):
        what.append("name or directions")
    _audit(repo, actor, role, "staff_gauge_update", f"staffgauge:{g.village_id}:{g.id}",
           "; ".join(what) or "no change")
    return new


def reading_for(repo: Repo, village_id: str, gauge_id: str, value: float) -> StaffReading:
    """The villager's choice, checked against the stored gauge."""
    g = repo.get_staff_gauge(village_id, gauge_id)
    if g is None or not g.active:
        raise StaffGaugeError("That reference point is not set up for this village.",
                              "यह निशान वाली जगह इस गाँव के लिए नहीं है।")
    m = mark_for(g, value)
    return StaffReading(gauge_id=g.id, gauge_name=g.name, mark=m.label, value=m.value, height_cm=m.height_cm,
                        chosen_at=clock.iso(clock.now()))


def confirm(repo: Repo, report: Report, *, value: float | None, unreadable: bool, actor: str, role: str) -> Report:
    """Officer confirms (value = the villager's mark), adjusts (another mark) or rejects the reading."""
    sr = report.staff_reading
    if sr is None:
        raise StaffGaugeError("This report has no staff gauge reading.", "इस सूचना में पैमाने की रीडिंग नहीं है।")
    g = repo.get_staff_gauge(report.village_id, sr.gauge_id)
    if g is None:
        raise StaffGaugeError("The reference point for this reading no longer exists.", "यह संदर्भ स्थान अब नहीं है।")
    now = clock.iso(clock.now())
    before = _describe(sr)
    if unreadable:
        new = sr.model_copy(update={"status": "unreadable", "confirmed_mark": None, "confirmed_value": None,
                                    "confirmed_height_cm": None, "confirmed_level": None, "confirmed_by": actor,
                                    "confirmed_at": now})
    else:
        if value is None:
            raise StaffGaugeError("Choose a mark to confirm.", "पुष्टि के लिए एक निशान चुनें।")
        m = mark_for(g, value)
        new = sr.model_copy(update={"status": "confirmed", "confirmed_mark": m.label, "confirmed_value": m.value,
                                    "confirmed_height_cm": m.height_cm, "confirmed_level": level_for(g, m.value),
                                    "confirmed_by": actor, "confirmed_at": now})
    updated = repo.update_report(report.id, staff_reading=new.model_dump())
    adjusted = new.status == "confirmed" and new.confirmed_value != sr.value
    _audit(repo, actor, role, "staff_reading_confirm", f"report:{report.id}",
           f"{before} -> {_describe(new)}" + (" (adjusted from the villager's mark)" if adjusted else ""))
    return updated


def _describe(sr: StaffReading) -> str:
    if sr.status == "confirmed":
        return f"confirmed {sr.confirmed_mark} ({sr.confirmed_level})"
    if sr.status == "unreadable":
        return "unreadable"
    return f"villager chose {sr.mark}, unconfirmed"


def public_reading(r: Report) -> dict[str, Any] | None:
    """A staff reading for the public village page: mark, time and whether an officer confirmed it."""
    sr = r.staff_reading
    if sr is None or r.state in {"duplicate", "false"}:
        return None
    confirmed = sr.status == "confirmed"
    return {"report_id": r.id, "gauge_id": sr.gauge_id, "gauge_name": sr.gauge_name, "at": r.created_at,
            "mark": sr.confirmed_mark if confirmed else sr.mark, "villager_mark": sr.mark, "status": sr.status,
            "level": sr.confirmed_level if confirmed else None, "confirmed_at": sr.confirmed_at,
            "replay": r.replay}


def village_view(repo: Repo, village_id: str, reports: list[Report]) -> dict[str, Any]:
    readings = [x for x in (public_reading(r) for r in reports) if x is not None]
    return {"gauges": [view(g) for g in active(repo, village_id)], "readings": readings[:10]}

