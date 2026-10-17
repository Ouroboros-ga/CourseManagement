"""Make each release's virtualenv independent of every other release.

Releases are built by copying a previous release's ``.venv``. Console scripts embed
an absolute interpreter path in their ``#!`` line, so a copied venv keeps pointing at
whichever release originally created it. Rewriting only the *source* release path is
not enough: the source already pointed at a third release, so nothing matched and
every release silently depended on a directory a later cleanup could delete.

Run with ``--apply`` after switching ``current``, then restart the service.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT_STR = "/opt/course-management"
ROOT = Path(ROOT_STR)
RELEASES = ROOT / "releases"
POINTER = ROOT / "current"

VENV_PATH = re.compile(
    rb"^#!(\S*/(?:releases|rehearsals)/[^/\n]+/backend/\.venv/bin/python[0-9.]*)\n"
)
# activate.sh/.csh/.fish/.nu/.bat each spell the assignment differently, so replace the
# embedded path itself instead of matching an assignment form. ROOT_STR stays a string on
# purpose: Path normalizes separators on Windows and would never match POSIX text.
EMBEDDED_VENV = re.compile(re.escape(ROOT_STR) + r"/(?:releases|rehearsals)/.*?/backend/\.venv")


def own_python(venv: Path) -> Path:
    return venv / "bin" / "python"


def fix_release(release: Path, apply: bool) -> tuple[int, int]:
    venv = release / "backend" / ".venv"
    if not own_python(venv).exists():
        return 0, 0
    target = str(own_python(venv)).encode()
    shebangs = 0
    for script in sorted((venv / "bin").iterdir()):
        if script.is_symlink() or not script.is_file():
            continue
        try:
            value = script.read_bytes()
        except OSError:
            continue
        first, separator, rest = value.partition(b"\n")
        match = VENV_PATH.match(first + b"\n") if first.startswith(b"#!") else None
        if not match or match.group(1) == target:
            continue
        if apply:
            script.write_bytes(b"#!" + target + separator + rest)
        shebangs += 1

    activations = 0
    if apply:
        for activate in (venv / "bin").glob("activate*"):
            try:
                text = activate.read_text(errors="ignore")
            except OSError:
                continue
            fixed = EMBEDDED_VENV.sub(str(venv), text)
            if fixed != text:
                activate.write_text(fixed)
                activations += 1
    return shebangs, activations


def verify(release: Path) -> str:
    launcher = release / "backend" / ".venv" / "bin" / "uvicorn"
    result = subprocess.run([str(launcher), "--version"], capture_output=True, text=True, timeout=90)
    if result.returncode != 0:
        raise RuntimeError(f"{release.name}: launcher broken -> {result.stderr.strip()[:200]}")
    return (result.stdout or result.stderr).strip()


def candidates(include: list[str]) -> list[Path]:
    if include:
        return [RELEASES / name for name in include]
    current = POINTER.resolve()
    return sorted({*RELEASES.glob("2*"), current}, key=lambda p: p.name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="rewrite files (default is a dry run)")
    parser.add_argument("--release", action="append", default=[], help="only this release name")
    args = parser.parse_args()

    pointer = POINTER.resolve()
    print(f"current: {pointer.name}   mode: {'APPLY' if args.apply else 'DRY RUN'}")
    broken = 0
    for release in candidates(args.release):
        if not release.is_dir():
            print(f"  missing {release.name}")
            broken += 1
            continue
        shebangs, activations = fix_release(release, args.apply)
        note = verify(release) if args.apply else "pending"
        print(f"{release.name}: shebangs={shebangs} activate={activations}  {note}")
    if args.apply and broken:
        return 1
    if not args.apply:
        print("dry run only; pass --apply to rewrite")
    return 0


if __name__ == "__main__":
    sys.exit(main())
