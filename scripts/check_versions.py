"""Check that the HACS integration and the add-on carry the same version, and the tag's if given.

    python scripts/check_versions.py            # manifest, config.yaml, Dockerfile agree
    python scripts/check_versions.py v0.2.0     # ... and all are 0.2.0

HACS shows the GitHub release tag, Home Assistant shows manifest.json, and the Supervisor offers
an add-on update only when config.yaml's version changes, so a release tag that disagrees with
either is a mistake. The add-on's Dockerfile builds on the engine image of the same version, which
release.yml publishes for the tag.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "custom_components" / "znacht" / "manifest.json"
ADDON = ROOT / "addon" / "znacht" / "config.yaml"
DOCKERFILE = ROOT / "addon" / "znacht" / "Dockerfile"


def addon_version() -> str:
    match = re.search(r"""^version:\s*["']?([^"'\s#]+)""", ADDON.read_text(), re.MULTILINE)
    if not match:
        sys.exit(f"no version in {ADDON.relative_to(ROOT)}")
    return match.group(1)


def addon_image_version() -> str:
    text = DOCKERFILE.read_text()
    match = re.search(r"^FROM\s+ghcr\.io/sbarkar/znacht:(\S+)", text, re.MULTILINE)
    if not match:
        sys.exit(f"no FROM ghcr.io/sbarkar/znacht:<version> in {DOCKERFILE.relative_to(ROOT)}")
    return match.group(1)


def main(argv: list[str]) -> int:
    found = {
        str(MANIFEST.relative_to(ROOT)): json.loads(MANIFEST.read_text())["version"],
        str(ADDON.relative_to(ROOT)): addon_version(),
        str(DOCKERFILE.relative_to(ROOT)): addon_image_version(),
    }
    expected = argv[0].removeprefix("v") if argv else next(iter(found.values()))
    wrong = {path: version for path, version in found.items() if version != expected}
    for path, version in wrong.items():
        print(f"{path}: {version}, expected {expected}", file=sys.stderr)
    if not wrong:
        print(f"version {expected}")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
