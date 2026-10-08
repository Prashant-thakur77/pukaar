"""Extract EN VO blocks from narration.md into per-block .txt files.

Output:
  docs/Project/video/raw/narration/B01.txt ... B08.txt
  docs/Project/video/raw/narration/_combined_en.txt    (concatenated)

Each .txt holds plain prose, no markdown. Pickup lines and forbidden lines
are not included.
"""

from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
VIDEO_DIR = HERE.parent
NARRATION_MD = VIDEO_DIR / "narration.md"
OUT_DIR = VIDEO_DIR / "raw" / "narration"
OUT_DIR.mkdir(parents=True, exist_ok=True)

BLOCK_RE = re.compile(
    r"^## (B0\d) —.*?\n(.*?)(?=^## |\Z)",
    re.S | re.M,
)


def clean_quote(text: str) -> str:
    """Strip leading '> ', collapse whitespace, drop markdown punctuation."""
    lines = [re.sub(r"^>\s?", "", ln).strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    return " ".join(lines)


def extract_en(block_body: str) -> str:
    """Pull lines that follow `EN:` and stop at `ES`, `---`, or `##`."""
    m = re.search(r"EN:\s*\n((?:>.*\n?)+)", block_body)
    if not m:
        return ""
    return clean_quote(m.group(1))


def main() -> int:
    src = NARRATION_MD.read_text(encoding="utf-8")
    blocks: list[tuple[str, str]] = []
    for match in BLOCK_RE.finditer(src):
        block_id, body = match.group(1), match.group(2)
        en = extract_en(body)
        if en:
            blocks.append((block_id, en))

    combined: list[str] = []
    for block_id, en in blocks:
        path = OUT_DIR / f"{block_id}.txt"
        path.write_text(en + "\n", encoding="utf-8")
        words = len(en.split())
        print(f"  {block_id}  {words:3d} words  -> {path.relative_to(VIDEO_DIR)}")
        combined.append(en)

    combined_path = OUT_DIR / "_combined_en.txt"
    combined_path.write_text("\n\n".join(combined) + "\n", encoding="utf-8")
    total = sum(len(b[1].split()) for b in blocks)
    print(f"  total {total} words -> {combined_path.relative_to(VIDEO_DIR)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
