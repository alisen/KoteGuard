"""Config management – read/write TOML for global and per-project config."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

import tomli_w

from koteguard.models import GlobalConfig, ProjectLocalConfig

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

KOTE_HOME = Path.home() / ".kote"
GLOBAL_CONFIG_PATH = KOTE_HOME / "config.toml"
TEMPLATES_DIR = KOTE_HOME / "templates"
SESSIONS_DIR = KOTE_HOME / "sessions"
WORKTREES_DIR = KOTE_HOME / "worktrees"
AUDIT_LOG_PATH = KOTE_HOME / "audit.jsonl"


def _ensure_kote_home() -> None:
    """Create ~/.kote directory structure if it doesn't exist."""
    for d in (KOTE_HOME, TEMPLATES_DIR, SESSIONS_DIR, WORKTREES_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Global config
# ---------------------------------------------------------------------------


def load_global_config() -> GlobalConfig:
    """Load (or create) ~/.kote/config.toml."""
    _ensure_kote_home()
    if not GLOBAL_CONFIG_PATH.exists():
        cfg = GlobalConfig()
        save_global_config(cfg)
        return cfg
    raw = tomllib.loads(GLOBAL_CONFIG_PATH.read_text(encoding="utf-8"))
    return GlobalConfig.model_validate(raw)


def save_global_config(cfg: GlobalConfig) -> None:
    """Persist global config to ~/.kote/config.toml."""
    _ensure_kote_home()
    data = cfg.model_dump(mode="json")
    data = {k: str(v) if isinstance(v, Path) else v for k, v in data.items()}
    GLOBAL_CONFIG_PATH.write_text(tomli_w.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Per-project config
# ---------------------------------------------------------------------------


def project_kote_dir(project_root: Path) -> Path:
    return project_root / ".kote"


def load_project_config(project_root: Path) -> ProjectLocalConfig:
    """Load per-project .kote/local.toml (git-ignored)."""
    cfg_path = project_kote_dir(project_root) / "local.toml"
    if not cfg_path.exists():
        return ProjectLocalConfig()
    raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    return ProjectLocalConfig.model_validate(raw)


def save_project_config(project_root: Path, cfg: ProjectLocalConfig) -> None:
    """Persist per-project .kote/local.toml."""
    kote_dir = project_kote_dir(project_root)
    kote_dir.mkdir(parents=True, exist_ok=True)
    data = cfg.model_dump(mode="json", exclude_none=True)
    (kote_dir / "local.toml").write_text(tomli_w.dumps(data), encoding="utf-8")


def ensure_project_gitignore(project_root: Path) -> None:
    """Add .kote/local.toml and .kote/history/ to the project .gitignore."""
    gi_path = project_root / ".gitignore"
    entries_needed = [".kote/local.toml", ".kote/history/"]

    existing = gi_path.read_text(encoding="utf-8") if gi_path.exists() else ""
    additions = [e for e in entries_needed if e not in existing]

    if additions:
        content = existing
        if content and not content.endswith("\n"):
            content += "\n"
        content += "\n".join(additions) + "\n"
        gi_path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Audit log (JSONL) – global
# ---------------------------------------------------------------------------


def append_audit(entry: dict[str, Any]) -> None:
    """Append a JSON-serialisable dict to the global JSONL audit log."""
    _ensure_kote_home()
    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def read_audit_log() -> list[dict[str, Any]]:
    """Return all entries from the JSONL audit log."""
    if not AUDIT_LOG_PATH.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in AUDIT_LOG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


# ---------------------------------------------------------------------------
# Per-session audit log
# ---------------------------------------------------------------------------


def append_session_audit(session_id: str, entry: dict[str, Any]) -> None:
    """Append an entry to the per-session audit.jsonl in sessions/{id}/logs/."""
    session_logs_dir = SESSIONS_DIR / session_id / "logs"
    session_logs_dir.mkdir(parents=True, exist_ok=True)
    audit_path = session_logs_dir / "audit.jsonl"
    with audit_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")

    # Also write to global audit log
    append_audit(entry)


def read_session_audit(session_id: str) -> list[dict[str, Any]]:
    """Return all per-session audit entries."""
    audit_path = SESSIONS_DIR / session_id / "logs" / "audit.jsonl"
    if not audit_path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


# ---------------------------------------------------------------------------
# Worktree context check
# ---------------------------------------------------------------------------


def check_worktree_context() -> bool:
    """Return True if CWD is inside a known kote worktree."""
    cwd = Path.cwd()
    if not SESSIONS_DIR.exists():
        return False
    for session_dir in SESSIONS_DIR.iterdir():
        meta_file = session_dir / "meta.json"
        if not meta_file.exists():
            continue
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            wt_path = Path(str(data.get("worktree_path", "")))
            if wt_path.exists() and (cwd == wt_path or cwd.is_relative_to(wt_path)):
                return True
        except Exception:
            pass
    return False
