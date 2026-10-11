"""Early-action checklists: the named people and small tasks that make a warning usable.

Practical Action's Nepal early-warning work rests on named people and drills.
Each village gets the same seven tasks; the pradhan (own village) or an
officer ticks them. Stored as VILLAGE#id / CHECKLIST#item with done_by and
done_at; every change is authorised by Cedar and written to the audit trail.
"""

from __future__ import annotations

from Pukaar.core import clock
from Pukaar.core.ids import new_id
from Pukaar.store.models import AuditRow, ChecklistItem
from Pukaar.store.repo import Repo

# (id, English, Hindi). NEEDS NATIVE-SPEAKER REVIEW like the UI strings.
DEFAULT_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("khad_watcher", "Khad watcher named", "खड्ड पर नज़र रखने वाला व्यक्ति तय"),
    ("shelter_open", "School or panchayat bhawan opened as shelter", "स्कूल या पंचायत भवन आश्रय के लिए खुला"),
    ("vulnerable_listed", "Elders and disabled people listed", "बुज़ुर्गों और दिव्यांग लोगों की सूची बनी"),
    ("telegram_checked", "Telegram sign-ups checked (/start <village>)", "टेलीग्राम पर जुड़े लोग जाँचे (/start <गाँव>)"),
    ("drill_run", "Drill run this month", "इस महीने अभ्यास (ड्रिल) हुआ"),
    ("firstaid_torches", "First-aid and torches ready", "प्राथमिक उपचार और टॉर्च तैयार"),
    ("livestock_moved", "Livestock moved from the riverbank", "मवेशी नदी किनारे से हटाए गए"),
)
ITEM_IDS = {i for i, _, _ in DEFAULT_ITEMS}


def defaults(village_id: str) -> list[ChecklistItem]:
    return [ChecklistItem(village_id=village_id, item=i, label_en=en, label_hi=hi, order=n)
            for n, (i, en, hi) in enumerate(DEFAULT_ITEMS)]


def seed(repo: Repo, village_id: str) -> None:
    """Add any missing default item; never resets one already ticked."""
    have = {c.item for c in repo.list_checklist(village_id)}
    for item in defaults(village_id):
        if item.item not in have:
            repo.put_checklist_item(item)


def items(repo: Repo, village_id: str) -> list[ChecklistItem]:
    stored = {c.item: c for c in repo.list_checklist(village_id)}
    out = [stored.get(d.item, d) for d in defaults(village_id)]
    return sorted(out, key=lambda c: c.order)


def view(repo: Repo, village_id: str) -> dict:
    rows = items(repo, village_id)
    return {"items": [c.model_dump() for c in rows], "done": sum(c.done for c in rows), "total": len(rows)}


def set_done(repo: Repo, village_id: str, item: str, done: bool, actor: str, role: str) -> ChecklistItem:
    if item not in ITEM_IDS:
        raise KeyError(item)
    current = next(c for c in items(repo, village_id) if c.item == item)
    now = clock.iso(clock.now())
    updated = current.model_copy(update={"done": done, "done_by": actor if done else None,
                                         "done_at": now if done else None})
    repo.put_checklist_item(updated)
    if current.done != done:
        repo.append_audit(AuditRow(at=now, id=new_id("aud"), actor=actor, role=role,
                                   action="checklist_tick" if done else "checklist_untick",
                                   resource=f"checklist:{village_id}:{item}", decision="allow",
                                   reason=f"{current.label_en}: {'done' if done else 'not done'}"))
    return updated
