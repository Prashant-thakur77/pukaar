"""Record a 1920x1080 screencast of the dashboard while
`scripts/demo_connectivity.py` runs end-to-end.

Output: docs/Project/video/raw/screencast_wifi_off_to_sync.mp4

Prereqs (start in two terminals before running):
  1.  ./scripts/setup.sh
  2.  PYTHONPATH=backend/src python3 -m Pukaar.scripts.seed
  3.  ./scripts/dev.sh                # backend on :8000, frontend on :5173

Usage:
  python3 docs/Project/video/scripts/capture_demo_connectivity.py
  FRONTEND_URL=http://127.0.0.1:5173 API_BASE=http://127.0.0.1:8000/api \
    python3 docs/Project/video/scripts/capture_demo_connectivity.py

Flags via env:
  RECORD_SECONDS    Total recording window (default 32)
  PRE_DEMO_DELAY    Seconds to record before launching demo (default 3)
  POST_DEMO_DELAY   Seconds to record after demo exits (default 4)
  KEEP_WEBM         "1" to keep the raw .webm alongside the .mp4
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[4]
VIDEO_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = VIDEO_DIR / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000/api").rstrip("/")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://127.0.0.1:5173")
RECORD_SECONDS = float(os.environ.get("RECORD_SECONDS", "32"))
PRE_DEMO_DELAY = float(os.environ.get("PRE_DEMO_DELAY", "3"))
POST_DEMO_DELAY = float(os.environ.get("POST_DEMO_DELAY", "4"))
KEEP_WEBM = os.environ.get("KEEP_WEBM", "0") == "1"
DEMO_SCRIPT = REPO_ROOT / "scripts" / "demo_connectivity.py"
OUTPUT_BASENAME = "screencast_wifi_off_to_sync"


def probe_services() -> None:
    """Fail fast if backend or frontend is not reachable."""
    try:
        with httpx.Client(timeout=4) as c:
            c.get(f"{API_BASE}/health").raise_for_status()
    except Exception as exc:
        sys.exit(f"backend unreachable at {API_BASE}/health: {exc}\n"
                 f"start it with `./scripts/dev.sh` first")

    try:
        with httpx.Client(timeout=4, follow_redirects=True) as c:
            r = c.get(FRONTEND_URL)
            if r.status_code >= 500:
                raise RuntimeError(f"status {r.status_code}")
    except Exception as exc:
        sys.exit(f"frontend unreachable at {FRONTEND_URL}: {exc}\n"
                 f"start it with `./scripts/dev.sh` first")

    if not DEMO_SCRIPT.exists():
        sys.exit(f"demo script missing: {DEMO_SCRIPT}")


def reencode_to_mp4(webm: Path, mp4: Path) -> bool:
    if not shutil.which("ffmpeg"):
        print("ffmpeg not on PATH; keeping .webm only", file=sys.stderr)
        return False
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(webm),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-crf", "18", "-preset", "slow",
        "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "192k",
        str(mp4),
    ]
    subprocess.run(cmd, check=True)
    return True


def main() -> int:
    probe_services()

    print(f"backend  ok  {API_BASE}")
    print(f"frontend ok  {FRONTEND_URL}")
    print(f"recording -> {RAW_DIR / (OUTPUT_BASENAME + '.mp4')} (target {RECORD_SECONDS:.0f}s)")

    started = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
            record_video_dir=str(RAW_DIR),
            record_video_size={"width": 1920, "height": 1080},
        )
        page = context.new_page()
        page.goto(FRONTEND_URL, wait_until="networkidle")
        page.wait_for_timeout(int(PRE_DEMO_DELAY * 1000))

        env = os.environ.copy()
        env.setdefault("API_BASE", API_BASE)
        proc = subprocess.Popen(
            [sys.executable, str(DEMO_SCRIPT)],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        # Print demo output while we keep the page open
        deadline = started + RECORD_SECONDS
        while time.time() < deadline:
            line = proc.stdout.readline() if proc.stdout else ""
            if line:
                print(line.rstrip())
            elif proc.poll() is not None:
                # Demo finished; hold the recording for POST_DEMO_DELAY
                page.wait_for_timeout(int(POST_DEMO_DELAY * 1000))
                break
            else:
                page.wait_for_timeout(200)

        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

        video_path = page.video.path() if page.video else None
        page.close()
        context.close()
        browser.close()

    if not video_path:
        sys.exit("playwright did not produce a video file")

    raw_webm = Path(video_path)
    out_webm = RAW_DIR / (OUTPUT_BASENAME + ".webm")
    out_mp4 = RAW_DIR / (OUTPUT_BASENAME + ".mp4")

    raw_webm.replace(out_webm)
    print(f"saved {out_webm.relative_to(VIDEO_DIR)}")

    if reencode_to_mp4(out_webm, out_mp4):
        print(f"saved {out_mp4.relative_to(VIDEO_DIR)}")
        if not KEEP_WEBM:
            out_webm.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
