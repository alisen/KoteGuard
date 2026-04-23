"""Comprehensive tests for koteguard/config.py.

Covers load/save global config, load/save project config, gitignore management,
audit log (global and per-session), resolve_android_cli_enabled, resolve_agent_mode,
check_worktree_context.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from koteguard.models import AgentMode, GlobalConfig, IDEChoice, ProjectLocalConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_kote_home(tmp_path: Path):
    """Context manager that redirects all KOTE_HOME-derived paths to tmp_path."""
    kote_home = tmp_path / ".kote"
    kote_home.mkdir(parents=True, exist_ok=True)
    return patch.multiple(
        "koteguard.config",
        KOTE_HOME=kote_home,
        GLOBAL_CONFIG_PATH=kote_home / "config.toml",
        TEMPLATES_DIR=kote_home / "templates",
        SESSIONS_DIR=kote_home / "sessions",
        WORKTREES_DIR=kote_home / "worktrees",
        AUDIT_LOG_PATH=kote_home / "audit.jsonl",
    )


# ---------------------------------------------------------------------------
# load_global_config / save_global_config
# ---------------------------------------------------------------------------


class TestGlobalConfig:
    def test_creates_default_when_missing(self, tmp_path):
        with _patch_kote_home(tmp_path):
            from koteguard.config import load_global_config

            cfg = load_global_config()
        assert isinstance(cfg, GlobalConfig)
        assert cfg.agent_mode == "copilot-cli"

    def test_saved_config_can_be_reloaded(self, tmp_path):
        with _patch_kote_home(tmp_path):
            from koteguard.config import load_global_config, save_global_config

            cfg = load_global_config()
            cfg.android_cli_enabled = False
            save_global_config(cfg)

            reloaded = load_global_config()
        assert reloaded.android_cli_enabled is False

    def test_saves_and_loads_agent_mode(self, tmp_path):
        with _patch_kote_home(tmp_path):
            from koteguard.config import load_global_config, save_global_config

            cfg = load_global_config()
            cfg.agent_mode = AgentMode.COPILOT_PLUGIN
            save_global_config(cfg)
            reloaded = load_global_config()
        assert reloaded.agent_mode == "copilot-plugin"

    def test_saves_and_loads_ide_choice(self, tmp_path):
        with _patch_kote_home(tmp_path):
            from koteguard.config import load_global_config, save_global_config

            cfg = load_global_config()
            cfg.default_ide = IDEChoice.ANDROID_STUDIO
            save_global_config(cfg)
            reloaded = load_global_config()
        assert reloaded.default_ide == "android"

    def test_creates_directory_structure(self, tmp_path):
        kote_home = tmp_path / ".kote"
        with _patch_kote_home(tmp_path):
            from koteguard.config import load_global_config

            load_global_config()
        assert kote_home.exists()
        assert (kote_home / "sessions").exists()
        assert (kote_home / "worktrees").exists()


# ---------------------------------------------------------------------------
# load_project_config / save_project_config
# ---------------------------------------------------------------------------


class TestProjectConfig:
    def test_returns_defaults_when_no_file(self, tmp_path):
        from koteguard.config import load_project_config

        cfg = load_project_config(tmp_path)
        assert isinstance(cfg, ProjectLocalConfig)
        assert cfg.last_session_id is None

    def test_save_and_reload(self, tmp_path):
        from koteguard.config import load_project_config, save_project_config

        cfg = ProjectLocalConfig(last_session_id="abc-1")
        save_project_config(tmp_path, cfg)
        reloaded = load_project_config(tmp_path)
        assert reloaded.last_session_id == "abc-1"

    def test_save_creates_kote_dir(self, tmp_path):
        from koteguard.config import save_project_config

        cfg = ProjectLocalConfig(last_session_id="abc-2")
        save_project_config(tmp_path, cfg)
        assert (tmp_path / ".kote" / "local.toml").exists()

    def test_save_android_cli_disabled(self, tmp_path):
        from koteguard.config import load_project_config, save_project_config

        cfg = ProjectLocalConfig(android_cli_enabled=False)
        save_project_config(tmp_path, cfg)
        reloaded = load_project_config(tmp_path)
        assert reloaded.android_cli_enabled is False

    def test_none_fields_not_written_to_file(self, tmp_path):
        """None fields should not appear in the TOML file."""
        from koteguard.config import save_project_config

        cfg = ProjectLocalConfig()  # all None except notes
        save_project_config(tmp_path, cfg)
        content = (tmp_path / ".kote" / "local.toml").read_text(encoding="utf-8")
        # last_session_id is None — should not appear in file
        assert "last_session_id" not in content


# ---------------------------------------------------------------------------
# ensure_project_gitignore
# ---------------------------------------------------------------------------


class TestEnsureProjectGitignore:
    def test_creates_gitignore_if_missing(self, tmp_path):
        from koteguard.config import ensure_project_gitignore

        ensure_project_gitignore(tmp_path)
        gi = tmp_path / ".gitignore"
        assert gi.exists()
        content = gi.read_text(encoding="utf-8")
        assert ".kote/local.toml" in content
        assert ".kote/history/" in content

    def test_appends_to_existing_gitignore(self, tmp_path):
        gi = tmp_path / ".gitignore"
        gi.write_text("*.pyc\n", encoding="utf-8")

        from koteguard.config import ensure_project_gitignore

        ensure_project_gitignore(tmp_path)
        content = gi.read_text(encoding="utf-8")
        assert "*.pyc" in content
        assert ".kote/local.toml" in content

    def test_idempotent_no_duplicates(self, tmp_path):
        from koteguard.config import ensure_project_gitignore

        ensure_project_gitignore(tmp_path)
        ensure_project_gitignore(tmp_path)
        content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
        assert content.count(".kote/local.toml") == 1

    def test_no_trailing_newline_issue(self, tmp_path):
        """Existing gitignore without trailing newline should still get correct additions."""
        gi = tmp_path / ".gitignore"
        gi.write_text("node_modules", encoding="utf-8")  # no trailing \n

        from koteguard.config import ensure_project_gitignore

        ensure_project_gitignore(tmp_path)
        content = gi.read_text(encoding="utf-8")
        assert ".kote/local.toml" in content


# ---------------------------------------------------------------------------
# audit log (global JSONL)
# ---------------------------------------------------------------------------


class TestAuditLog:
    def test_append_and_read_global_audit(self, tmp_path):
        with _patch_kote_home(tmp_path):
            from koteguard.config import append_audit, read_audit_log

            append_audit({"event": "test_event", "session_id": "s1"})
            append_audit({"event": "another_event", "session_id": "s2"})
            entries = read_audit_log()

        assert len(entries) == 2
        assert entries[0]["event"] == "test_event"
        assert entries[1]["event"] == "another_event"

    def test_read_returns_empty_when_no_log(self, tmp_path):
        with _patch_kote_home(tmp_path):
            from koteguard.config import read_audit_log

            entries = read_audit_log()
        assert entries == []

    def test_skips_malformed_json_lines(self, tmp_path):
        kote_home = tmp_path / ".kote"
        kote_home.mkdir(parents=True, exist_ok=True)
        audit_path = kote_home / "audit.jsonl"
        audit_path.write_text('{"event": "ok"}\nNOT JSON\n{"event": "also_ok"}\n', encoding="utf-8")
        with patch("koteguard.config.AUDIT_LOG_PATH", audit_path):
            from koteguard.config import read_audit_log

            entries = read_audit_log()
        assert len(entries) == 2


# ---------------------------------------------------------------------------
# per-session audit log
# ---------------------------------------------------------------------------


class TestSessionAuditLog:
    def test_append_and_read_session_audit(self, tmp_path):
        with _patch_kote_home(tmp_path):
            from koteguard.config import append_session_audit, read_session_audit

            entry = {"event": "session_created", "session_id": "test-sess"}
            append_session_audit("test-sess", entry)
            entries = read_session_audit("test-sess")

        assert len(entries) == 1
        assert entries[0]["event"] == "session_created"

    def test_session_audit_creates_logs_dir(self, tmp_path):
        with _patch_kote_home(tmp_path):
            from koteguard.config import SESSIONS_DIR, append_session_audit

            append_session_audit("sess-x", {"event": "e"})
            logs_dir = SESSIONS_DIR / "sess-x" / "logs"

        assert logs_dir.exists()

    def test_read_session_audit_missing_returns_empty(self, tmp_path):
        with _patch_kote_home(tmp_path):
            from koteguard.config import read_session_audit

            entries = read_session_audit("nonexistent-session")
        assert entries == []

    def test_session_audit_also_writes_to_global(self, tmp_path):
        with _patch_kote_home(tmp_path):
            from koteguard.config import append_session_audit, read_audit_log

            append_session_audit("my-sess", {"event": "cross_write"})
            global_entries = read_audit_log()

        assert any(e.get("event") == "cross_write" for e in global_entries)

    def test_multiple_entries_per_session(self, tmp_path):
        with _patch_kote_home(tmp_path):
            from koteguard.config import append_session_audit, read_session_audit

            append_session_audit("multi", {"event": "first"})
            append_session_audit("multi", {"event": "second"})
            entries = read_session_audit("multi")

        assert len(entries) == 2


# ---------------------------------------------------------------------------
# resolve_android_cli_enabled
# ---------------------------------------------------------------------------


class TestResolveAndroidCliEnabled:
    def test_uses_project_local_override_true(self, tmp_path):
        from koteguard.config import resolve_android_cli_enabled, save_project_config

        save_project_config(tmp_path, ProjectLocalConfig(android_cli_enabled=True))
        with _patch_kote_home(tmp_path):
            result = resolve_android_cli_enabled(tmp_path)
        assert result is True

    def test_uses_project_local_override_false(self, tmp_path):
        from koteguard.config import resolve_android_cli_enabled, save_project_config

        save_project_config(tmp_path, ProjectLocalConfig(android_cli_enabled=False))
        with _patch_kote_home(tmp_path):
            result = resolve_android_cli_enabled(tmp_path)
        assert result is False

    def test_falls_through_to_global_config(self, tmp_path):
        """When local config has no android_cli_enabled, global config is used."""
        with _patch_kote_home(tmp_path):
            from koteguard.config import (
                load_global_config,
                resolve_android_cli_enabled,
                save_global_config,
            )

            cfg = load_global_config()
            cfg.android_cli_enabled = False
            save_global_config(cfg)

            # No local config
            result = resolve_android_cli_enabled(tmp_path)
        assert result is False

    def test_returns_bool(self, tmp_path):
        with _patch_kote_home(tmp_path):
            from koteguard.config import resolve_android_cli_enabled

            result = resolve_android_cli_enabled(tmp_path)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# resolve_agent_mode
# ---------------------------------------------------------------------------


class TestResolveAgentMode:
    def test_returns_agent_mode_enum(self, tmp_path):
        with _patch_kote_home(tmp_path):
            from koteguard.config import resolve_agent_mode

            mode = resolve_agent_mode(tmp_path)
        assert isinstance(mode, AgentMode)

    def test_returns_configured_mode(self, tmp_path):
        with _patch_kote_home(tmp_path):
            from koteguard.config import (
                load_global_config,
                resolve_agent_mode,
                save_global_config,
            )

            cfg = load_global_config()
            cfg.agent_mode = AgentMode.COPILOT_PLUGIN
            save_global_config(cfg)
            mode = resolve_agent_mode()
        assert mode == AgentMode.COPILOT_PLUGIN

    def test_works_with_no_project_root(self, tmp_path):
        with _patch_kote_home(tmp_path):
            from koteguard.config import resolve_agent_mode

            mode = resolve_agent_mode(None)
        assert mode is not None


# ---------------------------------------------------------------------------
# check_worktree_context
# ---------------------------------------------------------------------------


class TestCheckWorktreeContext:
    def test_returns_false_when_sessions_dir_missing(self, tmp_path):
        nonexistent = tmp_path / "no-sessions"
        with patch("koteguard.config.SESSIONS_DIR", nonexistent):
            from koteguard.config import check_worktree_context

            result = check_worktree_context()
        assert result is False

    def test_returns_false_when_cwd_not_a_worktree(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        # Create a session meta pointing elsewhere
        sess_dir = sessions_dir / "sess-001"
        sess_dir.mkdir()
        meta = {
            "worktree_path": str(tmp_path / "other-location"),
            "session_id": "sess-001",
        }
        (sess_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

        with patch("koteguard.config.SESSIONS_DIR", sessions_dir):
            from koteguard.config import check_worktree_context

            result = check_worktree_context()
        assert result is False

    def test_returns_true_when_cwd_is_worktree(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        worktree_path = tmp_path / "worktree"
        worktree_path.mkdir()

        sess_dir = sessions_dir / "sess-x"
        sess_dir.mkdir()
        meta = {
            "worktree_path": str(worktree_path),
            "session_id": "sess-x",
        }
        (sess_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

        with (
            patch("koteguard.config.SESSIONS_DIR", sessions_dir),
            patch("koteguard.config.Path.cwd", return_value=worktree_path),
        ):
            from koteguard.config import check_worktree_context

            result = check_worktree_context()
        assert result is True

    def test_skips_missing_meta_files(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        # Dir without meta.json
        (sessions_dir / "orphan-sess").mkdir()

        with patch("koteguard.config.SESSIONS_DIR", sessions_dir):
            from koteguard.config import check_worktree_context

            result = check_worktree_context()
        assert result is False

    def test_skips_invalid_json_meta(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        sess_dir = sessions_dir / "bad-sess"
        sess_dir.mkdir()
        (sess_dir / "meta.json").write_text("NOT JSON", encoding="utf-8")

        with patch("koteguard.config.SESSIONS_DIR", sessions_dir):
            from koteguard.config import check_worktree_context

            result = check_worktree_context()
        assert result is False


# ---------------------------------------------------------------------------
# project_kote_dir
# ---------------------------------------------------------------------------


class TestProjectKoteDir:
    def test_returns_kote_subdir(self, tmp_path):
        from koteguard.config import project_kote_dir

        result = project_kote_dir(tmp_path)
        assert result == tmp_path / ".kote"
