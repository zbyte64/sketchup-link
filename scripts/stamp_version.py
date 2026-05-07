#!/usr/bin/env python3
"""
Reads the canonical VERSION file at the repo root and stamps it into
blender_manifest.toml and pyproject.toml (both at blender_plugin/).

Usage:
    python scripts/stamp_version.py

The VERSION file contains a single line with the version string (e.g. "1.1.0").
This script is called by CI before packaging the Python addon extension.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = REPO_ROOT / "VERSION"

FILES_TO_STAMP = [
    REPO_ROOT / "blender_plugin" / "blender_manifest.toml",
    REPO_ROOT / "blender_plugin" / "pyproject.toml",
]

VERSION_PATTERN = re.compile(
    r'^(version\s*=\s*)"([^"]+)"',
    re.MULTILINE,
)


def read_version() -> str:
    if not VERSION_FILE.exists():
        print(f"ERROR: VERSION file not found at {VERSION_FILE}", file=sys.stderr)
        sys.exit(1)
    version = VERSION_FILE.read_text().strip()
    if not re.match(r"^\d+\.\d+\.\d+$", version):
        print(
            f"ERROR: VERSION file does not contain a valid semver string: '{version}'",
            file=sys.stderr,
        )
        sys.exit(1)
    return version


def stamp_file(path: Path, version: str) -> bool:
    if not path.exists():
        print(f"WARNING: {path} not found, skipping")
        return False

    original = path.read_text()
    updated, count = VERSION_PATTERN.subn(r'\1"' + version + '"', original)
    if count == 0:
        print(f"WARNING: No 'version = \"...\"' line found in {path}")
        return False
    path.write_text(updated)
    print(f"Stamped {path} with version {version}")
    return True


def main() -> None:
    version = read_version()
    ok = True
    for filepath in FILES_TO_STAMP:
        if not stamp_file(filepath, version):
            ok = False
    if not ok:
        sys.exit(1)
    print(f"All files stamped with version {version}")


if __name__ == "__main__":
    main()
