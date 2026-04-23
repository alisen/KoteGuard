#!/usr/bin/env python3
"""
Update the Supported Versions table in SECURITY.md to match the
version declared in pyproject.toml.

Usage:
    python .github/scripts/update_security_version.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def get_version() -> str:
    pyproject = ROOT / "pyproject.toml"
    text = pyproject.read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        sys.exit("ERROR: Could not find version in pyproject.toml")
    return match.group(1)


def update_security_md(path: Path, version: str) -> bool:
    """Return True if the file was changed."""
    text = path.read_text()

    # Replace the "latest" row — matches any version string in that column
    new_text = re.sub(
        r"(\|\s*)[\w.\-]+ \(latest\)(\s*\|\s*✅\s*\|)",
        rf"\g<1>{version} (latest)\g<2>",
        text,
    )
    # Replace the "older than X" row
    new_text = re.sub(
        r"(\|\s*< )[\w.\-]+(\s*\|\s*❌\s*\|)",
        rf"\g<1>{version}\g<2>",
        new_text,
    )

    if new_text == text:
        return False

    path.write_text(new_text)
    return True


def main() -> None:
    version = get_version()
    print(f"Version from pyproject.toml: {version}")

    target = ROOT / "SECURITY.md"
    changed = update_security_md(target, version)
    status = "UPDATED" if changed else "already up-to-date"
    print(f"  {status}: SECURITY.md")
    print("Done — SECURITY.md updated." if changed else "Done — nothing to change.")


if __name__ == "__main__":
    main()
