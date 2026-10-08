"""Headless 1920x1080 screenshots of every ui_scenes/*.html.

Run from repo root:

    python3 docs/Project/video/scripts/screenshot_scenes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
VIDEO_DIR = HERE.parent
SCENES = sorted((VIDEO_DIR / "ui_scenes").glob("*.html"))
OUT_DIR = VIDEO_DIR / "raw" / "screenshots"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    if not SCENES:
        print("no scenes found", file=sys.stderr)
        return 1

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
        )
        page = context.new_page()

        for scene in SCENES:
            url = scene.as_uri()
            page.goto(url, wait_until="networkidle")
            page.wait_for_timeout(150)
            out = OUT_DIR / (scene.stem + ".png")
            page.screenshot(path=str(out), full_page=False, clip={
                "x": 0, "y": 0, "width": 1920, "height": 1080,
            })
            print(f"  {scene.name:42s} -> {out.relative_to(VIDEO_DIR)}")

        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
