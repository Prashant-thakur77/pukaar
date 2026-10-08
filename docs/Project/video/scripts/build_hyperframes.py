"""Scaffold HyperFrames projects from ui_scenes/*.html.

Produces 7 standalone projects under docs/Project/video/hyperframes/:

  title_card/        scene 01, 5s
  pukaar/             scene 02 -> scene 03 (crossfade), 18s
  evidence_pack/     scene 04, 10s
  reasoning_chain/   scene 05, 25s
  sinagir_export/    scene 06, 15s
  end_card/          scene 08, 8s
  litoral_map/       scene 09, 6s

Each project contains an index.html that is a single HyperFrames composition.
Run `cd <project> && npx hyperframes lint && npx hyperframes render` to render.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from textwrap import dedent

HERE = Path(__file__).resolve().parent
VIDEO_DIR = HERE.parent
SCENES_DIR = VIDEO_DIR / "ui_scenes"
HF_DIR = VIDEO_DIR / "hyperframes"


def read_scene(name: str) -> tuple[str, str]:
    """Return (head_style, body_inner) extracted from a ui_scene HTML file."""
    src = (SCENES_DIR / name).read_text(encoding="utf-8")

    style_match = re.search(r"<style>(.*?)</style>", src, re.S)
    style = style_match.group(1).strip() if style_match else ""

    body_match = re.search(r"<body>(.*?)</body>", src, re.S)
    body_inner = body_match.group(1).strip() if body_match else ""

    return style, body_inner


def copy_shared_css(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SCENES_DIR / "_shared.css", target)


def write_project(name: str, duration: float, html_body: str) -> None:
    proj = HF_DIR / name
    proj.mkdir(parents=True, exist_ok=True)
    copy_shared_css(proj / "_shared.css")

    duration = float(duration)
    index = dedent(f"""\
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8" />
      <title>{name} — HyperFrames</title>
      <link rel="stylesheet" href="_shared.css" />
      <style>
        html, body {{
          margin: 0;
          padding: 0;
          background: var(--bg);
          width: 1920px;
          height: 1080px;
          overflow: hidden;
        }}
      </style>
    </head>
    <body>
      <div data-composition-id="{name}" data-start="0" data-width="1920" data-height="1080" data-duration="{duration}" style="width:1920px;height:1080px;position:relative;">
        {html_body}
      </div>
      <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
      <script>
        window.__timelines = window.__timelines || {{}};
        const tl = gsap.timeline({{ paused: true }});
        {ANIMATIONS[name]}
        // Pad timeline to target duration so the final state holds
        tl.to({{}}, {{ duration: Math.max(0.1, {duration} - tl.totalDuration()) }});
        window.__timelines["{name}"] = tl;
      </script>
    </body>
    </html>
    """)
    (proj / "index.html").write_text(index, encoding="utf-8")
    (proj / "hyperframes.config.json").write_text(
        dedent(f"""\
        {{
          "name": "{name}",
          "duration": {duration},
          "fps": 30,
          "width": 1920,
          "height": 1080
        }}
        """),
        encoding="utf-8",
    )


# Per-project GSAP timelines. Layout-before-animation: scenes are positioned
# at their hero frame; tl.from() animates entrance, tl.to() animates exit only
# on the final beat of each clip (HF guidance allows fades on terminal scene).
ANIMATIONS = {
    "title_card": dedent("""\
        tl.from(".brand",   { y: 60, opacity: 0, duration: 1.0, ease: "power3.out" }, 0.2);
        tl.from(".tagline", { y: 30, opacity: 0, duration: 0.9, ease: "power2.out" }, 0.8);
        tl.from(".meta",    { opacity: 0, duration: 0.7, ease: "power2.out" }, 1.6);
        tl.from(".watermark", { opacity: 0, duration: 0.6, ease: "none" }, 0.4);
    """),

    "end_card": dedent("""\
        tl.from(".brand",    { y: 50, opacity: 0, duration: 1.0, ease: "power3.out" }, 0.2);
        tl.from(".tagline",  { y: 24, opacity: 0, duration: 0.8, ease: "power2.out" }, 0.7);
        tl.from(".roadmap",  { y: 24, opacity: 0, duration: 0.8, ease: "power3.out" }, 1.3);
        tl.from(".roadmap .step.now",   { color: "#e6edf3", duration: 0.6, ease: "none" }, 1.7);
        tl.from(".roadmap .step.next",  { color: "#8aa0b6", duration: 0.6, ease: "none" }, 2.0);
        tl.from(".repo",     { opacity: 0, duration: 0.6, ease: "power2.out" }, 2.4);
        tl.from(".credit",   { opacity: 0, duration: 0.6, ease: "power2.out" }, 2.9);
        tl.from(".laurel",   { opacity: 0, duration: 0.6, ease: "power2.out" }, 3.4);
        tl.from(".watermark", { opacity: 0, duration: 0.5, ease: "none" }, 0.4);
    """),

    "litoral_map": dedent("""\
        tl.from("h1.title",   { y: 28, opacity: 0, duration: 0.7, ease: "power3.out" }, 0.2);
        tl.from("p.subtitle", { y: 18, opacity: 0, duration: 0.5, ease: "power2.out" }, 0.5);
        tl.from(".ar-base",   { opacity: 0, duration: 0.8, ease: "power2.out" }, 0.8);
        tl.from(".ar-litoral",{ opacity: 0, duration: 0.7, ease: "power2.out" }, 1.4);
        tl.from(".river",     { opacity: 0, duration: 0.6, ease: "power2.out" }, 1.8);
        tl.from(".node-marker", { scale: 0.6, opacity: 0, transformOrigin: "center", duration: 0.6, stagger: 0.35, ease: "back.out(1.8)" }, 2.2);
        tl.from(".legend",    { x: -20, opacity: 0, duration: 0.6, ease: "power2.out" }, 3.6);
        tl.from(".caption-strip", { x: 20, opacity: 0, duration: 0.6, ease: "power2.out" }, 3.8);
        tl.from(".watermark", { opacity: 0, duration: 0.5, ease: "none" }, 0.4);
    """),

    "pukaar": dedent("""\
        // Scene A: input phone (0–7.5s)
        tl.set(".scene-a", { autoAlpha: 1 }, 0);
        tl.set(".scene-b", { autoAlpha: 0 }, 0);
        tl.from(".scene-a .stage-header", { y: 30, opacity: 0, duration: 0.8, ease: "power3.out" }, 0.2);
        tl.from(".scene-a .phone",        { y: 60, opacity: 0, duration: 0.9, ease: "power3.out" }, 0.5);
        tl.from(".scene-a .input-text",   { opacity: 0, duration: 0.7, ease: "power2.out" }, 1.2);
        tl.from(".scene-a .voice-bar span", { scaleY: 0, transformOrigin: "bottom", duration: 0.5, stagger: 0.04, ease: "power2.out" }, 1.6);
        tl.from(".scene-a .send",         { y: 30, opacity: 0, duration: 0.6, ease: "expo.out" }, 2.4);

        // Crossfade A -> B at 8.0s
        tl.to(".scene-a", { autoAlpha: 0, duration: 0.6, ease: "power1.inOut" }, 8.0);
        tl.to(".scene-b", { autoAlpha: 1, duration: 0.6, ease: "power1.inOut" }, 8.2);

        // Scene B: structured JSON (8.6–18s)
        tl.from(".scene-b .stage > h1.title", { y: 30, opacity: 0, duration: 0.7, ease: "power3.out" }, 8.6);
        tl.from(".scene-b .stage > p.subtitle", { y: 20, opacity: 0, duration: 0.5, ease: "power2.out" }, 8.9);
        tl.from(".scene-b .panel:first-child", { x: -60, opacity: 0, duration: 0.7, ease: "power3.out" }, 9.2);
        tl.from(".scene-b .panel:last-child",  { x:  60, opacity: 0, duration: 0.7, ease: "power3.out" }, 9.5);
        tl.from(".scene-b pre.code", { opacity: 0, duration: 0.6, ease: "power2.out" }, 10.2);
        tl.from(".scene-b .footer-tag", { opacity: 0, duration: 0.5, ease: "power2.out" }, 16.5);
    """),

    "evidence_pack": dedent("""\
        tl.from(".header-row > div:first-child", { y: 30, opacity: 0, duration: 0.7, ease: "power3.out" }, 0.2);
        tl.from(".header-row .label-strip .badge", { y: 20, opacity: 0, duration: 0.5, stagger: 0.12, ease: "expo.out" }, 0.6);
        tl.from(".panel:first-child", { x: -50, opacity: 0, duration: 0.7, ease: "power3.out" }, 0.9);
        tl.from(".frames .frame-thumb", { y: 40, opacity: 0, duration: 0.55, stagger: 0.18, ease: "power3.out" }, 1.4);
        tl.from(".panel:first-child .label-strip .badge", { y: 14, opacity: 0, duration: 0.4, stagger: 0.08, ease: "power2.out" }, 2.4);
        tl.from(".panel:first-child .kv > *", { opacity: 0, duration: 0.4, stagger: 0.05, ease: "none" }, 3.0);
        tl.from(".panel:last-child", { x: 50, opacity: 0, duration: 0.7, ease: "power3.out" }, 4.0);
        tl.from(".panel:last-child pre.code", { opacity: 0, duration: 0.6, ease: "power2.out" }, 4.7);
        tl.from(".watermark", { opacity: 0, duration: 0.5, ease: "none" }, 0.0);
    """),

    "reasoning_chain": dedent("""\
        tl.from("h1.title", { y: 30, opacity: 0, duration: 0.7, ease: "power3.out" }, 0.2);
        tl.from("p.subtitle", { y: 20, opacity: 0, duration: 0.5, ease: "power2.out" }, 0.5);
        tl.from(".alert-card", { x: -60, opacity: 0, duration: 0.8, ease: "power3.out" }, 0.9);
        tl.from(".alert-card .level", { scale: 0.85, opacity: 0, duration: 0.6, ease: "back.out(2)" }, 1.5);
        tl.from(".alert-card .reasoning", { opacity: 0, duration: 0.6, ease: "power2.out" }, 2.2);
        tl.from(".alert-card .ribbon .badge", { y: 16, opacity: 0, duration: 0.4, stagger: 0.1, ease: "expo.out" }, 3.0);

        tl.from(".panel:last-child", { x: 60, opacity: 0, duration: 0.8, ease: "power3.out" }, 4.0);
        tl.from(".trace .step", { x: 40, opacity: 0, duration: 0.45, stagger: 0.45, ease: "power3.out" }, 4.8);
        tl.from(".ev-thumbs .frame-thumb", { y: 30, opacity: 0, duration: 0.5, stagger: 0.12, ease: "power3.out" }, 8.5);
        tl.from(".panel:last-child .ribbon .badge", { y: 14, opacity: 0, duration: 0.4, stagger: 0.1, ease: "power2.out" }, 10.0);
        tl.from(".watermark", { opacity: 0, duration: 0.5, ease: "none" }, 0.0);
    """),

    "sinagir_export": dedent("""\
        tl.from("h1.title", { y: 30, opacity: 0, duration: 0.7, ease: "power3.out" }, 0.2);
        tl.from("p.subtitle", { y: 20, opacity: 0, duration: 0.5, ease: "power2.out" }, 0.5);

        tl.from(".panel:first-child", { x: -50, opacity: 0, duration: 0.8, ease: "power3.out" }, 0.9);
        tl.from(".endpoint", { scale: 0.92, opacity: 0, duration: 0.6, ease: "back.out(1.6)" }, 1.4);
        tl.from(".field-list > *", { x: -20, opacity: 0, duration: 0.35, stagger: 0.08, ease: "power2.out" }, 2.2);
        tl.from(".pulse", { scale: 0.85, opacity: 0, duration: 0.5, ease: "back.out(2)" }, 4.0);

        tl.from(".panel:last-child", { x: 50, opacity: 0, duration: 0.8, ease: "power3.out" }, 1.5);
        tl.from(".panel:last-child pre.code", { opacity: 0, duration: 0.7, ease: "power2.out" }, 2.4);

        tl.from(".footer", { y: 16, opacity: 0, duration: 0.6, ease: "power2.out" }, 12.0);
        tl.from(".watermark", { opacity: 0, duration: 0.5, ease: "none" }, 0.0);
    """),
}


def pukaar_body() -> str:
    """Combine scenes 02 and 03 into stacked, absolute-positioned layers."""
    style_a, body_a = read_scene("02_volunteer_report_input.html")
    style_b, body_b = read_scene("03_volunteer_report_json.html")

    # Strip outer "stage" wrapping so we can place each scene as a layer,
    # then wrap each in our own absolutely-positioned scene container.
    a_inner = body_a
    b_inner = body_b

    return dedent(f"""\
    <style>{style_a}</style>
    <style>{style_b}</style>
    <style>
      .scene-layer {{
        position: absolute; inset: 0;
        width: 1920px; height: 1080px;
      }}
      .scene-a, .scene-b {{ will-change: opacity; }}
    </style>
    <div class="scene-layer scene-a">
      {a_inner}
    </div>
    <div class="scene-layer scene-b">
      {b_inner}
    </div>
    """)


def single_scene_body(scene_filename: str) -> str:
    style, body_inner = read_scene(scene_filename)
    return dedent(f"""\
    <style>{style}</style>
    {body_inner}
    """)


def main() -> int:
    HF_DIR.mkdir(parents=True, exist_ok=True)

    write_project("title_card",       duration=5.0,  html_body=single_scene_body("01_title_card.html"))
    write_project("pukaar",            duration=18.0, html_body=pukaar_body())
    write_project("evidence_pack",    duration=10.0, html_body=single_scene_body("04_fixed_node_evidence_pack.html"))
    write_project("reasoning_chain",  duration=25.0, html_body=single_scene_body("05_alert_reasoning_chain.html"))
    write_project("sinagir_export",   duration=15.0, html_body=single_scene_body("06_sinagir_export.html"))
    write_project("end_card",         duration=8.0,  html_body=single_scene_body("08_end_card.html"))
    write_project("litoral_map",      duration=6.0,  html_body=single_scene_body("09_litoral_map.html"))

    print("Built HyperFrames projects:")
    for proj in sorted(HF_DIR.iterdir()):
        if proj.is_dir():
            print(f"  - {proj.relative_to(VIDEO_DIR)}")
    print()
    print("Render with:")
    print("  cd docs/Project/video/hyperframes/<name> && npx hyperframes render --output ../../raw/hf_<name>.mp4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
