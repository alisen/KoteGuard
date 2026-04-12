"""Config management – read/write TOML for global and per-project config."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import tomli_w

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

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
    # Convert Path values to strings for TOML serialisation
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
    """Add .kote/local.toml to the project .gitignore if not already there."""
    gi_path = project_root / ".gitignore"
    entry = ".kote/local.toml\n"
    if gi_path.exists():
        content = gi_path.read_text(encoding="utf-8")
        if ".kote/local.toml" not in content:
            gi_path.write_text(content + entry, encoding="utf-8")
    else:
        gi_path.write_text(entry, encoding="utf-8")


# ---------------------------------------------------------------------------
# Audit log (JSONL)
# ---------------------------------------------------------------------------


def append_audit(entry: dict[str, Any]) -> None:
    """Append a JSON-serialisable dict to the JSONL audit log."""
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
