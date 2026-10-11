"""Build the README charts as SVG from the repo's own data (no numbers typed in).

    python3 scripts/build_charts.py      ->  docs/charts/*.svg

Sources: data/backtest.json (the back-test, built by the real rules) and
frontend/src/data/story-gohar-2023.json (Gohar's July 2023 replay, hour by hour).
Colours are the app's tokens (frontend/src/theme.css): cream, ink, sand gold,
forest, crimson, plus the level colours.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "charts"
CREAM, INK, INK3, LINE = "#f4ece4", "#0c0c08", "#5e5848", "#d9cdb9"
GOLD, FOREST, CRIMSON, KHAKI = "#d4ac58", "#0c4830", "#a01418", "#c8b488"
LEVEL = {"normal": "#1f9468", "watch": "#e7b800", "warning": "#ef6a1c", "critical": "#c8173f"}
FONT = "Inter, 'Segoe UI', Helvetica, Arial, sans-serif"
DISPLAY = "Anton, 'Bebas Neue', Impact, 'Arial Narrow', sans-serif"
IST = timezone(timedelta(hours=5, minutes=30))


def svg(w: int, h: int, body: str, title: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img">'
            f"<title>{escape(title)}</title>"
            f'<rect width="{w}" height="{h}" rx="18" fill="{CREAM}"/>{body}</svg>\n')


def text(x, y, s, size=14, fill=INK, weight=500, anchor="start", family=FONT, extra=""):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}" {extra}>{escape(str(s))}</text>')


def header(eyebrow: str, title: str, w: int) -> str:
    return (text(36, 44, eyebrow.upper(), 11, "#7a5a14", 800, extra='letter-spacing="2.4"')
            + text(36, 84, title.upper(), 34, INK, 400, family=DISPLAY, extra='letter-spacing="0.5"'))


def gohar_chart(story: dict) -> str:
    W, H = 960, 470
    L, R, T, B = 70, 30, 120, 96
    pts = story["points"]
    n = len(pts)
    ymax = 140.0
    x = lambda i: L + i / (n - 1) * (W - L - R)
    y = lambda mm: T + (1 - min(mm, ymax) / ymax) * (H - T - B)
    body = header("Gohar, Mandi · July 2023 · replayed through the real rules", "Everything needed was already in the forecast", W)
    for mm in (0, 50, 100):
        body += f'<line x1="{L}" x2="{W - R}" y1="{y(mm):.1f}" y2="{y(mm):.1f}" stroke="{LINE}" stroke-width="1"/>'
        body += text(L - 10, y(mm) + 4, mm, 11, INK3, 600, "end")
    for key, col in (("watch", LEVEL["watch"]), ("warning", LEVEL["warning"])):
        mm = story["imd_bands_mm"][key]
        body += f'<line x1="{L}" x2="{W - R}" y1="{y(mm):.1f}" y2="{y(mm):.1f}" stroke="{col}" stroke-width="1.6" stroke-dasharray="6 5"/>'
        body += text(W - R, y(mm) - 7, f"IMD {mm} mm · {key}", 11, col if key != "watch" else "#8a6a00", 800, "end")
    path = " ".join(f"{'M' if i == 0 else 'L'}{x(i):.1f},{y(p['rain_24h_mm'] or 0):.1f}" for i, p in enumerate(pts))
    area = path + f" L{x(n - 1):.1f},{y(0):.1f} L{x(0):.1f},{y(0):.1f} Z"
    body += f'<path d="{area}" fill="{GOLD}" fill-opacity="0.18"/>'
    body += f'<path d="{path}" fill="none" stroke="{INK}" stroke-width="2.6" stroke-linejoin="round"/>'
    # level ribbon: the level the rules set each hour
    rb = H - B + 22
    seg_w = (W - L - R) / (n - 1)
    for i, p in enumerate(pts[:-1]):
        body += f'<rect x="{x(i):.1f}" y="{rb}" width="{seg_w + 0.6:.1f}" height="14" fill="{LEVEL[p["level"]]}"/>'
    body += text(L - 10, rb + 11, "level", 10, INK3, 700, "end")
    idx = {p["at"]: i for i, p in enumerate(pts)}
    for k, (key, label) in enumerate((("watch", "Watch"), ("warning", "Warning"), ("critical", "Critical"))):
        at = story["first"][key]
        i = idx[at]
        when = datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(IST).strftime("%-d Jul %-I:%M %p IST")
        body += f'<line x1="{x(i):.1f}" x2="{x(i):.1f}" y1="{T - 6}" y2="{rb + 14}" stroke="{INK}" stroke-width="1" stroke-dasharray="2 3"/>'
        body += f'<circle cx="{x(i):.1f}" cy="{y(pts[i]["rain_24h_mm"] or 0):.1f}" r="5" fill="{LEVEL[key]}" stroke="{INK}" stroke-width="1.5"/>'
        body += text(x(i) + 6, T - 10 + k * 15, f"{label} · {when}", 11.5, INK, 800)
    # day ticks
    for i, p in enumerate(pts):
        if p["at"].endswith("T00:00:00Z"):
            d = datetime.fromisoformat(p["at"].replace("Z", "+00:00")).strftime("%-d Jul")
            body += text(x(i), H - B + 56, d, 11, INK3, 700, "middle")
    body += text(L, H - 14, f"Forecast rain for the next 24 h, hour by hour, as the 15-minute sweep would read it (mm). "
                 f"First Watch came {story['lead_hours_watch_to_peak_day']:.0f} h before the river's peak day.", 11.5, INK3, 600)
    return svg(W, H, body, "Gohar July 2023 back-test: rain forecast against IMD bands, with levels")


def lead_chart(bt: dict) -> str:
    sc = next(s for s in bt["scenarios"] if s["name"] == "himachal_2023_07")
    vs = sc["villages"]
    W, H = 960, 380
    L, R, T = 150, 60, 120
    row = 44
    vmax = max(v["lead_hours_watch_to_peak_day"] or 0 for v in vs) or 1
    body = header("Back-test · 7-11 July 2023 · archived forecasts", "Hours of warning before the river's peak day", W)
    for k, v in enumerate(vs):
        yy = T + k * row
        lead = v["lead_hours_watch_to_peak_day"] or 0
        top = "critical" if v["first_critical"] else "warning" if v["first_warning"] else "watch"
        w = (W - L - R - 200) * lead / vmax
        body += text(L - 14, yy + 21, v["village"], 15, INK, 800, "end")
        body += f'<rect x="{L}" y="{yy + 6}" width="{W - L - R - 80}" height="22" rx="11" fill="{LINE}" fill-opacity="0.45"/>'
        if w > 0:
            body += f'<rect x="{L}" y="{yy + 6}" width="{w:.1f}" height="22" rx="11" fill="{GOLD if top != "critical" else CRIMSON}"/>'
        body += text(L + max(w, 0) + 10, yy + 22, f"{lead:.0f} h", 15, INK, 800)
        body += text(W - R, yy + 22, f"reached {top}", 11.5, LEVEL[top] if top != "watch" else "#8a6a00", 800, "end")
    body += text(L, H - 18, "From the first Watch to the day of peak river flow. Archived forecasts are later reanalyses, so read these as an upper bound.", 11.5, INK3, 600)
    return svg(W, H, body, "Back-test lead time per village, July 2023")


def years_chart(bt: dict) -> str:
    a = next(s for s in bt["scenarios"] if s["name"] == "himachal_2023_07")
    b = next(s for s in bt["scenarios"] if s["name"] != "himachal_2023_07")
    names = [v["village"] for v in a["villages"]]
    rain_a = {v["village"]: v["max_rain_24h_mm"] or 0 for v in a["villages"]}
    rain_b = {v["village"]: v["max_rain_24h_mm"] or 0 for v in b["villages"]}
    W, H = 960, 450
    L, R, T, B = 70, 30, 120, 96
    ymax = 140.0
    y = lambda mm: T + (1 - min(mm, ymax) / ymax) * (H - T - B)
    body = header("Same rules, two monsoons", "July 2023 was forecast. The 2025 cloudburst was not.", W)
    for mm in (0, 50, 100):
        body += f'<line x1="{L}" x2="{W - R}" y1="{y(mm):.1f}" y2="{y(mm):.1f}" stroke="{LINE}"/>'
        body += text(L - 10, y(mm) + 4, mm, 11, INK3, 600, "end")
    band = 64.5
    body += f'<line x1="{L}" x2="{W - R}" y1="{y(band):.1f}" y2="{y(band):.1f}" stroke="{LEVEL["watch"]}" stroke-width="1.6" stroke-dasharray="6 5"/>'
    gx = L + (W - L - R) / len(names) * 2  # the gap between the 2nd and 3rd village
    body += text(gx, y(band) - 20, "IMD heavy rain", 10.5, "#8a6a00", 800, "middle") + text(gx, y(band) - 7, f"{band} mm", 10.5, "#8a6a00", 800, "middle")
    gw = (W - L - R) / len(names)
    bw = 34
    for i, nm in enumerate(names):
        cx = L + gw * i + gw / 2
        for j, (val, col) in enumerate(((rain_a[nm], INK), (rain_b[nm], CRIMSON))):
            bx = cx - bw - 3 + j * (bw + 6)
            body += f'<rect x="{bx:.1f}" y="{y(val):.1f}" width="{bw}" height="{y(0) - y(val):.1f}" rx="6" fill="{col}"/>'
            body += text(bx + bw / 2, y(val) - 6, f"{val:g}", 11, col, 800, "middle")
        body += text(cx, H - B + 22, nm, 13, INK, 800, "middle")
    body += f'<rect x="{L}" y="{H - 42}" width="12" height="12" rx="3" fill="{INK}"/>' + text(L + 18, H - 32, a["title"], 12, INK, 700)
    body += f'<rect x="{L + 300}" y="{H - 42}" width="12" height="12" rx="3" fill="{CRIMSON}"/>' + text(L + 318, H - 32, b["title"], 12, INK, 700)
    body += text(L, H - 6, "Peak 24 h forecast rain per village (mm), archived Open-Meteo forecasts, same rules for both years", 11, INK3, 600)
    return svg(W, H, body, "Peak forecast rain per village, July 2023 against 30 June 2025")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    story = json.loads((ROOT / "frontend/src/data/story-gohar-2023.json").read_text(encoding="utf-8"))
    bt = json.loads((ROOT / "data/backtest.json").read_text(encoding="utf-8"))
    for name, body in (("gohar-2023.svg", gohar_chart(story)), ("backtest-lead.svg", lead_chart(bt)), ("two-monsoons.svg", years_chart(bt))):
        (OUT / name).write_text(body, encoding="utf-8")
        print(OUT / name)


if __name__ == "__main__":
    main()
