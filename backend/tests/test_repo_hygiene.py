"""Repository-level checks: README links resolve, no local-model code is left."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_every_relative_link_in_readme_resolves():
    for doc in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]:
        text = doc.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)\s]+)\)", text):
            if target.startswith(("http://", "https://", "mailto:", "#", "tel:")):
                continue
            path = (doc.parent / target.split("#", 1)[0]).resolve()
            assert path.exists(), f"{doc.name} links to missing {target}"


def test_no_local_model_left():
    out = subprocess.run(
        ["git", "grep", "-Iil", "-e", "gemma", "-e", "ollama", "-e", "litert", "-e", "whisper", "-e", "mediapipe",
         "--", "backend", "frontend", "scripts", ":!backend/tests/test_repo_hygiene.py", ":!*.lock", ":!*package-lock.json"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert out.stdout.strip() == "", out.stdout
