#!/usr/bin/env python3
"""Sync bundled Android skill guides from github.com/android/skills.

Used by .github/workflows/sync-android-skills.yml (nightly).
Also usable locally:

    GITHUB_TOKEN=ghp_... python .github/scripts/sync_android_skills.py

Exit codes:
  0 – success (files may or may not have changed)
  1 – network / API error
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

REPO_OWNER = "android"
REPO_NAME = "skills"
API_BASE = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents"

# KoteGuard maps official leaf-directory names → our bundled *.skill.md filenames.
# If the leaf name already matches what we want, no entry is needed.
# Add entries here when Google renames directories or we want a friendlier alias.
NAME_MAP: dict[str, str] = {
    "agp-9-upgrade": "agp9",
    "navigation-3": "navigation3",
    "migrate-xml-views-to-jetpack-compose": "compose-migration",
    "edge-to-edge": "edge-to-edge",
    "r8-analyzer": "r8-analyzer",
    "play-billing-library-version-upgrade": "play-billing",
}

# Destination: bundled skills directory inside KoteGuard repo
REPO_ROOT = Path(__file__).parent.parent.parent
DEST_DIR = REPO_ROOT / "templates" / "android-skills"


def _api_get(path: str) -> list[dict]:
    url = f"{API_BASE}/{path}".rstrip("/")
    token = os.environ.get("GITHUB_TOKEN")
    headers: dict[str, str] = {"User-Agent": "KoteGuard/sync-android-skills"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def _find_skill_files(path: str = "", depth: int = 0) -> list[tuple[str, str]]:
    """Recursively return [(leaf_dir_name, download_url), …] for every SKILL.md."""
    if depth > 5:
        return []
    try:
        items = _api_get(path)
    except Exception as exc:
        print(f"  WARNING: API error at '{path or '/'}': {exc}", file=sys.stderr)
        return []
    found = []
    for item in items:
        if item["name"].startswith("."):
            continue
        if item["type"] == "file" and item["name"] == "SKILL.md":
            leaf = path.split("/")[-1] if path else "unknown"
            found.append((leaf, item["download_url"]))
        elif item["type"] == "dir":
            found.extend(_find_skill_files(item["path"], depth + 1))
    return found


def _download(url: str) -> str:
    token = os.environ.get("GITHUB_TOKEN")
    headers: dict[str, str] = {"User-Agent": "KoteGuard/sync-android-skills"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8")


def main() -> None:
    print(f"Fetching skill list from github.com/{REPO_OWNER}/{REPO_NAME} …")
    try:
        skill_refs = _find_skill_files()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if not skill_refs:
        print("WARNING: no SKILL.md files found. Check connectivity.", file=sys.stderr)
        sys.exit(1)

    DEST_DIR.mkdir(parents=True, exist_ok=True)

    added = updated = unchanged = errors = 0
    for leaf_name, download_url in sorted(skill_refs):
        # Map to our preferred filename
        friendly_name = NAME_MAP.get(leaf_name, leaf_name)
        dest = DEST_DIR / f"{friendly_name}.skill.md"

        try:
            content = _download(download_url)
        except Exception as exc:
            print(f"  ERROR downloading {leaf_name}: {exc}", file=sys.stderr)
            errors += 1
            continue

        if dest.exists():
            existing = dest.read_text(encoding="utf-8")
            if existing == content:
                print(f"  — {friendly_name}  (unchanged)")
                unchanged += 1
                continue
            dest.write_text(content, encoding="utf-8")
            print(f"  ↑ {friendly_name}  (updated)")
            updated += 1
        else:
            dest.write_text(content, encoding="utf-8")
            print(f"  + {friendly_name}  (new)")
            added += 1

    print(f"\nDone: {added} new, {updated} updated, {unchanged} unchanged, {errors} errors.")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
