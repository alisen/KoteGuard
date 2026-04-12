"""Phase 2 – Sensitive file stubs.

Creates placeholder files in the worktree so the agent knows these files
exist conceptually, without exposing real secrets.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Sensitive file patterns
# ---------------------------------------------------------------------------

ANDROID_SENSITIVE: dict[str, str] = {
    "*.jks": "ANDROID_KEYSTORE_STUB",
    "*.keystore": "ANDROID_KEYSTORE_STUB",
    "google-services.json": "GOOGLE_SERVICES_STUB",
    "local.properties": "LOCAL_PROPERTIES_STUB",
}

IOS_SENSITIVE: dict[str, str] = {
    "*.p12": "IOS_CERT_STUB",
    "*.mobileprovision": "IOS_PROVISION_STUB",
    "GoogleService-Info.plist": "GOOGLE_SERVICE_INFO_STUB",
}

# ---------------------------------------------------------------------------
# Stub content templates
# ---------------------------------------------------------------------------

_STUB_CONTENT: dict[str, str] = {
    "ANDROID_KEYSTORE_STUB": (
        "# KoteGuard STUB\n"
        "# This is a placeholder for a real Android keystore file.\n"
        "# The real file is NOT present in this worktree for security reasons.\n"
        "# DO NOT commit real keystore files.\n"
    ),
    "GOOGLE_SERVICES_STUB": """\
{
  "__kote_stub__": true,
  "__note__": "KoteGuard placeholder – real google-services.json is NOT here.",
  "project_info": {
    "project_number": "000000000000",
    "project_id": "stub-project-id",
    "storage_bucket": "stub-project-id.appspot.com"
  },
  "client": []
}
""",
    "LOCAL_PROPERTIES_STUB": (
        "# KoteGuard STUB\n"
        "# sdk.dir and ndk.dir paths are machine-specific.\n"
        "# This file is intentionally empty – do not commit.\n"
        "sdk.dir=/PATH/TO/ANDROID/SDK\n"
    ),
    "IOS_CERT_STUB": (
        "# KoteGuard STUB\n"
        "# This is a placeholder for a real iOS certificate (.p12).\n"
        "# The real file is NOT present in this worktree.\n"
    ),
    "IOS_PROVISION_STUB": (
        "# KoteGuard STUB\n"
        "# This is a placeholder for a real iOS provisioning profile.\n"
        "# The real file is NOT present in this worktree.\n"
    ),
    "GOOGLE_SERVICE_INFO_STUB": """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>__kote_stub__</key><true/>
  <key>__note__</key>
  <string>KoteGuard placeholder – real GoogleService-Info.plist is NOT here.</string>
  <key>BUNDLE_ID</key><string>com.example.stub</string>
  <key>PROJECT_ID</key><string>stub-project-id</string>
</dict>
</plist>
""",
}

_DEFAULT_STUB = "# KoteGuard STUB – real file not present in worktree\n"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class SensitiveFileHandler:
    """Creates stub files in a worktree for known sensitive file patterns."""

    def __init__(self, worktree_path: Path) -> None:
        self.worktree_path = worktree_path

    def inject_stubs(
        self, project_type: str = "unknown", source_root: Path | None = None
    ) -> list[Path]:
        """
        Scan *source_root* (defaults to worktree_path) for real sensitive
        files; for each found, ensure a stub exists in the worktree.

        Returns a list of stub paths created.
        """
        source_root = source_root or self.worktree_path
        created: list[Path] = []

        patterns = _resolve_patterns(project_type)
        for pattern, stub_key in patterns.items():
            matched = list(source_root.rglob(pattern))

            for real_file in matched:
                # Compute relative path, place stub in worktree
                try:
                    rel = real_file.relative_to(source_root)
                except ValueError:
                    rel = Path(real_file.name)

                stub_path = self.worktree_path / rel
                if not stub_path.exists():
                    stub_path.parent.mkdir(parents=True, exist_ok=True)
                    content = _STUB_CONTENT.get(stub_key, _DEFAULT_STUB)
                    stub_path.write_text(content, encoding="utf-8")
                    created.append(stub_path)

        return created

    def create_stub(self, relative_path: str, stub_key: str = "") -> Path:
        """Manually create a single stub file by relative path."""
        stub_path = self.worktree_path / relative_path
        stub_path.parent.mkdir(parents=True, exist_ok=True)
        content = _STUB_CONTENT.get(stub_key, _DEFAULT_STUB)
        stub_path.write_text(content, encoding="utf-8")
        return stub_path

    def is_stub(self, path: Path) -> bool:
        """Return True if the file looks like a KoteGuard stub."""
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            return "KoteGuard STUB" in content or '"__kote_stub__": true' in content
        except OSError:
            return False


def _resolve_patterns(project_type: str) -> dict[str, str]:
    """Merge sensitive patterns for a given project type."""
    combined: dict[str, str] = {}
    pt = project_type.lower()
    if pt in ("android", "monorepo", "flutter", "react_native"):
        combined.update(ANDROID_SENSITIVE)
    if pt in ("ios", "monorepo", "flutter", "react_native"):
        combined.update(IOS_SENSITIVE)
    # For unknown types, include all
    if pt == "unknown":
        combined.update(ANDROID_SENSITIVE)
        combined.update(IOS_SENSITIVE)
    return combined
