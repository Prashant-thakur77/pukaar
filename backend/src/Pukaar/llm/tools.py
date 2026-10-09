"""Read-only data tools for the agents. Plain functions plus Strands wrappers.

No tool sends, approves or changes a level. Every number an agent may quote
comes from one of these results.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable

from Pukaar.core import clock
from Pukaar.store.models import level_rank
from Pukaar.store.repo import Repo


class DataTools:
    def __init__(self, repo: Repo, charts: dict[str, Any] | None = None) -> None:
        self.repo = repo
        self.charts = charts if charts is not None else {}

    def _village(self, village_id: str):
        v = self.repo.get_village(village_id.lower().strip())
        if v is None:
            ids = [x.id for x in self.repo.list_villages()]
            raise ValueError(f"unknown village '{village_id}'; known: {', '.join(ids)}")
        return v

    # -- drafting agent ------------------------------------------------------
    def get_village_risk(self, village_id: str) -> dict:
        v = self._village(village_id)
        readings = self.repo.list_readings(v.id, limit=1)
        r = readings[0] if readings else None
        return {"village_id": v.id, "name": v.name, "name_hi": v.name_hi, "level": v.level,
                "level_since": v.level_since,
                "latest_reading": r.model_dump(exclude={"rain_hourly"}) if r else None,
                "thresholds": v.thresholds.model_dump() if v.thresholds else None}

    def get_recent_reports(self, village_id: str, hours: int = 6) -> list[dict]:
        v = self._village(village_id)
        since = clock.iso(clock.now() - timedelta(hours=hours))
        return [{"id": r.id, "at": r.created_at, "type": r.report_type, "severity": r.severity,
                 "state": r.state, "summary_en": r.summary_en, "label": "UNVERIFIED"
                 if r.state in {"received", "transcribing", "unverified"} else "verified"}
                for r in self.repo.list_reports(v.id, limit=20) if r.created_at >= since]

    def get_past_events(self, village_id: str) -> list[dict]:
        v = self._village(village_id)
        return [e.model_dump() for e in self.repo.list_past_events(v.id)]

    def get_safe_places(self, village_id: str) -> list[dict]:
        self._village(village_id)
        return []  # safe-places map is a stretch item; no verified places stored yet

    # -- analyst agent -------------------------------------------------------
    def rank_villages(self) -> list[dict]:
        out = []
        for v in self.repo.list_villages():
            r = self.repo.list_readings(v.id, limit=1)
            out.append({"village_id": v.id, "name": v.name, "level": v.level,
                        "rain_24h_mm": r[0].rain_24h_mm if r else None,
                        "discharge_peak": r[0].discharge_peak if r else None,
                        "warning_threshold": v.thresholds.warning if v.thresholds else None})
        out.sort(key=lambda x: (-level_rank(x["level"]), -(x["discharge_peak"] or 0) / ((x["warning_threshold"] or 1))))
        self.charts["rank_villages"] = {
            "type": "bar", "title": "Forecast peak discharge as share of warning threshold", "x_label": "Village",
            "y_label": "% of warning threshold",
            "series": [{"name": "peak / warning", "points": [
                {"x": x["name"], "y": round(100 * (x["discharge_peak"] or 0) / x["warning_threshold"], 1)}
                for x in out if x["warning_threshold"]]}],
        }
        return out

    def query_readings(self, village_id: str, hours: int = 48) -> dict:
        v = self._village(village_id)
        rows = list(reversed(self.repo.list_readings(v.id, limit=max(1, min(hours * 4, 384)))))
        points = [{"at": r.at, "rain_24h_mm": r.rain_24h_mm, "discharge_peak": r.discharge_peak, "replay": r.replay}
                  for r in rows]
        self.charts[f"readings:{v.id}"] = {
            "type": "line", "title": f"{v.name}: forecast rain (24 h) and river peak", "x_label": "Time (UTC)",
            "y_label": "mm / m³/s",
            "series": [
                {"name": "rain next 24 h (mm)", "points": [{"x": p["at"], "y": p["rain_24h_mm"]} for p in points if p["rain_24h_mm"] is not None]},
                {"name": "river peak (m³/s)", "points": [{"x": p["at"], "y": p["discharge_peak"]} for p in points if p["discharge_peak"] is not None]},
            ],
        }
        return {"village_id": v.id, "count": len(points), "readings": points[-12:]}

    def query_alerts(self, status: str = "", village_id: str = "") -> list[dict]:
        alerts = self.repo.list_alerts(status=status or None, village_id=village_id or None, limit=50)
        return [{"id": a.id, "village": a.village_name, "level": a.level, "status": a.status, "created_at": a.created_at,
                 "approved": a.approved, "delivered": a.delivered_count, "acknowledged": a.acknowledged_count,
                 "replay": a.replay} for a in alerts]

    def query_deliveries(self, unacknowledged_only: bool = True) -> list[dict]:
        out = []
        for a in self.repo.list_alerts(limit=50):
            for d in self.repo.list_deliveries(a.id):
                if unacknowledged_only and d.acknowledged_at:
                    continue
                out.append({"alert_id": a.id, "village": a.village_name, "recipient": d.name, "status": d.status,
                            "sent_at": d.sent_at, "attempts": d.attempts, "acknowledged_at": d.acknowledged_at})
        return out

    def query_reports(self, village_id: str = "", hours: int = 24) -> list[dict]:
        since = clock.iso(clock.now() - timedelta(hours=hours))
        villages = [self._village(village_id)] if village_id else self.repo.list_villages()
        out = []
        for v in villages:
            for r in self.repo.list_reports(v.id, limit=50):
                if r.created_at >= since:
                    out.append({"id": r.id, "village_id": v.id, "at": r.created_at, "type": r.report_type,
                                "severity": r.severity, "state": r.state, "lat": r.lat, "lon": r.lon})
        counts: dict[str, int] = {}
        for r in out:
            counts[r["village_id"]] = counts.get(r["village_id"], 0) + 1
        self.charts["reports_by_village"] = {
            "type": "bar", "title": f"Reports in the last {hours} h", "x_label": "Village", "y_label": "Reports",
            "series": [{"name": "reports", "points": [{"x": k, "y": n} for k, n in sorted(counts.items())]}],
        }
        return out

    def village_stats(self, village_id: str) -> dict:
        v = self._village(village_id)
        alerts = self.repo.list_alerts(village_id=v.id, limit=100)
        return {"village_id": v.id, "level": v.level, "alerts": len(alerts),
                "alerts_by_level": {lvl: sum(1 for a in alerts if a.level == lvl) for lvl in ("watch", "warning", "critical")},
                "reports": len(self.repo.list_reports(v.id, limit=200)),
                "past_events": len(self.repo.list_past_events(v.id))}

    # -- Strands wrappers ------------------------------------------------------
    def strands_tools(self, names: list[str]) -> list[Callable]:
        from strands import tool

        docs = {
            "get_village_risk": "Current level, latest reading and thresholds for a village. Args: village_id",
            "get_recent_reports": "Villager reports from the last hours (UNVERIFIED ones labelled). Args: village_id, hours",
            "get_past_events": "Recorded past flood events for a village. Args: village_id",
            "get_safe_places": "Verified safe places for a village. Args: village_id",
            "rank_villages": "All villages ranked by level and forecast river peak against the warning threshold.",
            "query_readings": "Forecast rain and river-peak readings for a village over recent hours. Args: village_id, hours",
            "query_alerts": "Alerts, optionally filtered by status (comma list) and village_id.",
            "query_deliveries": "Alert deliveries; by default only those never acknowledged.",
            "query_reports": "Villager reports in the last hours, optionally for one village_id.",
            "village_stats": "Counts of alerts, reports and past events for a village. Args: village_id",
        }
        wrapped = []
        for name in names:
            fn = getattr(self, name)
            wrapped.append(tool(name=name, description=docs[name])(fn))
        return wrapped
