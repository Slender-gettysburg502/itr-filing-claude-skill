#!/usr/bin/env python3
"""
package_for_claude_app.py -- build a ZIP of this skill that claude.ai will
accept, for people using the Claude app rather than Claude Code.

    python scripts/package_for_claude_app.py

Writes itr2-india.zip next to the repo. Upload it at Customize > Skills.

Two things the app needs that Claude Code does not care about:

  * The ZIP must contain the skill folder at its root, so it unpacks as
    itr2-india/SKILL.md rather than SKILL.md.
  * The frontmatter description is capped at 200 characters. This skill's
    description is deliberately long, because a rich description is what makes
    Claude Code reach for the skill unprompted. So the packaged copy carries a
    trimmed description while the repo keeps the full one.

Nothing in the repo is modified. The trimming happens on the copy.
"""

import re
import shutil
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_NAME = "itr2-india"
OUT = ROOT / f"{SKILL_NAME}.zip"

# Under 200 characters, and still says enough for the app to pick the skill.
SHORT_DESCRIPTION = (
    "Files an Indian ITR-2 for AY 2026-27: reconciles Form 16, AIS, 26AS and "
    "broker statements, classifies capital gains, compares tax regimes, and "
    "builds the return JSON."
)

INCLUDE = ["SKILL.md", "references", "scripts", "assets", "schema"]


def trimmed_skill_md():
    text = (ROOT / "SKILL.md").read_text()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise SystemExit("SKILL.md has no YAML frontmatter.")
    front, body = m.group(1), m.group(2)

    out, skipping = [], False
    for line in front.split("\n"):
        if line.startswith("description:"):
            out.append(f"description: {SHORT_DESCRIPTION}")
            skipping = True
            continue
        # Drop the continuation lines of a folded description.
        if skipping:
            if line and not line[0].isspace():
                skipping = False
            else:
                continue
        out.append(line)
    return "---\n" + "\n".join(out) + "\n---\n" + body


def main():
    if len(SHORT_DESCRIPTION) > 200:
        raise SystemExit(f"SHORT_DESCRIPTION is {len(SHORT_DESCRIPTION)} "
                         f"characters. The app caps it at 200.")

    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / SKILL_NAME
        staged.mkdir()
        (staged / "SKILL.md").write_text(trimmed_skill_md())
        for name in INCLUDE:
            src = ROOT / name
            if name == "SKILL.md" or not src.exists():
                continue
            shutil.copytree(src, staged / name,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

        if OUT.exists():
            OUT.unlink()
        with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
            for path in sorted(staged.rglob("*")):
                if path.is_file():
                    z.write(path, path.relative_to(staged.parent))

    size = OUT.stat().st_size / 1024 / 1024
    print(f"wrote {OUT.name} ({size:.1f} MB)")
    print(f"description trimmed to {len(SHORT_DESCRIPTION)} characters "
          f"for the 200 character cap")
    print("\nUpload it at claude.ai: Customize > Skills > + > Create skill > "
          "Upload a skill.")
    print("Code execution must be on first, under Settings > Capabilities.")


if __name__ == "__main__":
    main()
