#!/usr/bin/env python3
"""Set one cache-bust version for every static asset import.

Usage: update ASSET_VERSION below, then run: python scripts/bump_asset_version.py

Keeping this in one command prevents browser ES modules from loading separate
instances of shared modules because their query-string URLs differ.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
ASSET_VERSION = "20260819-2"
VERSION_PATTERN = re.compile(r"(?<=\?v=)\d{8}-\d+")


def bump(version: str = ASSET_VERSION) -> list[Path]:
    if not re.fullmatch(r"\d{8}-\d+", version):
        raise ValueError("version must use YYYYMMDD-N, for example 20260819-2")

    changed: list[Path] = []
    for path in [*STATIC.glob("*.js"), STATIC / "index.html"]:
        source = path.read_text(encoding="utf-8")
        updated = VERSION_PATTERN.sub(version, source)
        if updated != source:
            path.write_text(updated, encoding="utf-8")
            changed.append(path)
    return changed


if __name__ == "__main__":
    if len(sys.argv) != 1:
        raise SystemExit("Update ASSET_VERSION in this script, then run it without arguments.")
    for changed_path in bump():
        print(changed_path.relative_to(ROOT))
