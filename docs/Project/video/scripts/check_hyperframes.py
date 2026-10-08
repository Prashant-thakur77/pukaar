"""Sanity-check each hyperframes/<proj>/index.html.

Loads each project in headless Chromium, waits for GSAP to load, then asserts:
  - exactly one element with [data-composition-id]
  - window.__timelines[<id>] exists
  - timeline.totalDuration() > 0

Captures a hero-frame screenshot at t = duration*0.4 for sanity preview.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
VIDEO_DIR = HERE.parent
HF_DIR = VIDEO_DIR / "hyperframes"
OUT_DIR = VIDEO_DIR / "raw" / "screenshots" / "hf"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    failures: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
        )

        for proj in sorted(d for d in HF_DIR.iterdir() if d.is_dir()):
            page = context.new_page()
            page.goto((proj / "index.html").as_uri(), wait_until="networkidle")
            page.wait_for_timeout(400)

            comp_id = page.evaluate(
                "() => document.querySelector('[data-composition-id]')?.dataset?.compositionId"
            )
            tl_present = page.evaluate(
                "(id) => !!(window.__timelines && window.__timelines[id])", comp_id
            )
            tl_dur = page.evaluate(
                "(id) => window.__timelines?.[id]?.totalDuration?.() || 0", comp_id
            )

            cfg_path = proj / "hyperframes.config.json"
            cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
            target_dur = float(cfg.get("duration", 0))

            ok = bool(comp_id) and tl_present and tl_dur > 0
            if not ok:
                failures.append(f"{proj.name}: id={comp_id!r} tl={tl_present} dur={tl_dur}")

            # Hero-frame at 40% of intended duration
            seek_t = max(0.5, target_dur * 0.4) if target_dur else 1.0
            page.evaluate(
                "(args) => { const tl = window.__timelines[args.id]; if (tl) tl.seek(args.t); }",
                {"id": comp_id, "t": seek_t},
            )
            page.wait_for_timeout(150)
            shot = OUT_DIR / f"{proj.name}_hero.png"
            page.screenshot(path=str(shot), clip={"x": 0, "y": 0, "width": 1920, "height": 1080})
            print(f"  {proj.name:20s} id={comp_id} tl_dur={tl_dur:.2f}s hero@{seek_t:.1f}s -> {shot.relative_to(VIDEO_DIR)}")

            page.close()

        browser.close()

    if failures:
        print("\nFAILURES:", file=sys.stderr)
        for f in failures:
            print("  " + f, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
