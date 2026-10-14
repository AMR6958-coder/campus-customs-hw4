"""Build the hand-in archive without secrets or installed dependencies.

Run from the project folder::

    python make_submission.py

Writes ``hw4.zip`` next to this file (its top-level folder is ``hw4``). The working
copy is left untouched, so the servers keep running from it.

Left out of the archive:

* ``backend/.env`` (the real gateway key and session secret; ``.env.example``
  is included instead)
* ``backend/.venv/``, ``frontend/node_modules/``, ``frontend/dist/``
* ``__pycache__/`` and ``*.pyc``
* ``data.zip`` (the original download; ``data/`` holds the same files)
* any other ``*.zip``, including earlier copies of this archive

After writing, the script re-opens the archive and checks that no entry is
named ``.env`` and that neither secret value appears in any text entry.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / "hw4.zip"
TOP_FOLDER = "hw4"

EXCLUDED_DIRS = {".git", ".venv", "node_modules", "dist", "__pycache__", ".pytest_cache"}
EXCLUDED_FILES = {".env", ".DS_Store", "Thumbs.db"}
EXCLUDED_SUFFIXES = {".pyc", ".zip"}
TEXT_SUFFIXES = {".py", ".md", ".json", ".ts", ".tsx", ".css", ".html", ".txt", ".example", ".svg", ".toml", ".cfg"}


def wanted(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if any(part in EXCLUDED_DIRS for part in rel.parts):
        return False
    if path.name in EXCLUDED_FILES or path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    return path.is_file()


def secrets_from_env() -> dict[str, str]:
    env = ROOT / "backend" / ".env"
    if not env.exists():
        return {}
    found = {}
    for line in env.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*([A-Z_]+)\s*=\s*(.+?)\s*$", line)
        if m and m.group(1) in ("PORTKEY_API_KEY", "SESSION_SECRET", "MYPORTKEY_API_KEY"):
            value = m.group(2).strip().strip('"').strip("'")
            if value and not value.startswith("replace-me"):
                found[m.group(1)] = value
    return found


def build() -> list[Path]:
    files = sorted(p for p in ROOT.rglob("*") if wanted(p))
    with zipfile.ZipFile(ARCHIVE, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, f"{TOP_FOLDER}/{p.relative_to(ROOT).as_posix()}")
    return files


def verify(secrets: dict[str, str]) -> list[str]:
    problems: list[str] = []
    with zipfile.ZipFile(ARCHIVE) as zf:
        names = zf.namelist()
        for name in names:
            base = name.rsplit("/", 1)[-1]
            if base == ".env":
                problems.append(f"{name} is in the archive")
            if "/.venv/" in name or "/node_modules/" in name:
                problems.append(f"{name} should have been excluded")
        for name in names:
            if Path(name).suffix.lower() not in TEXT_SUFFIXES:
                continue
            text = zf.read(name).decode("utf-8", errors="ignore")
            for key, value in secrets.items():
                if value in text:
                    problems.append(f"{key} value appears in {name}")
    return problems


def main() -> int:
    secrets = secrets_from_env()
    files = build()
    problems = verify(secrets)
    size_mb = ARCHIVE.stat().st_size / 1_000_000
    top = sorted({p.relative_to(ROOT).parts[0] for p in files})
    print(f"Wrote {ARCHIVE.name}: {len(files)} files, {size_mb:.1f} MB")
    print("Top level:", ", ".join(top))
    print("Checked:", ", ".join(secrets) or "no secrets found in backend/.env")
    if problems:
        print("PROBLEMS:")
        for p in problems:
            print("  -", p)
        ARCHIVE.unlink()
        print("Archive deleted; fix the problems and run again.")
        return 1
    print("No .env entry and no secret values inside the archive.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
