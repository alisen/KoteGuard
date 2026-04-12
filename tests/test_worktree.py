"""Tests for the worktree engine."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from koteguard.models import SessionStatus
from koteguard.worktree import (
    WorktreeEngine,
    _slugify,
    list_sessions,
    load_session,
    save_session,
)
from koteguard.models import SessionMeta


# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_basic(self):
        assert _slugify("My Cool App") == "my-cool-app"

    def test_special_chars(self):
        assert _slugify("Hello World!@#") == "hello-world"

    def test_leading_trailing_dashes(self):
        result = _slugify("---hello---")
        assert not result.startswith("-")
        assert not result.endswith("-")

    def test_max_length(self):
        long_str = "a" * 100
        assert len(_slugify(long_str)) <= 40

    def test_empty_string(self):
        assert _slugify("") == "project"


# ---------------------------------------------------------------------------
# save / load session
# ---------------------------------------------------------------------------


class TestSessionPersistence:
    def test_save_and_load(self, tmp_path):
        meta = SessionMeta(
            session_id="test-01",
            project_slug="my-app",
            project_root=tmp_path,
            worktree_path=tmp_path / "wt",
            branch_name="kote/test-01-task",
        )
        with patch("koteguard.worktree.SESSIONS_DIR", tmp_path / "sessions"):
            save_session(meta)
            loaded = load_session("test-01")

        assert loaded is not None
        assert loaded.session_id == "test-01"
        assert loaded.project_slug == "my-app"

    def test_load_nonexistent(self, tmp_path):
        with patch("koteguard.worktree.SESSIONS_DIR", tmp_path / "sessions"):
            result = load_session("does-not-exist")
        assert result is None

    def test_list_sessions_empty(self, tmp_path):
        with patch("koteguard.worktree.SESSIONS_DIR", tmp_path / "sessions"):
            result = list_sessions()
        assert result == []

    def test_list_sessions(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        metas = []
        for i in range(3):
            meta = SessionMeta(
                session_id=f"sess-0{i}",
                project_slug="proj",
                project_root=tmp_path,
                worktree_path=tmp_path / f"wt{i}",
                branch_name=f"kote/sess-0{i}",
            )
            metas.append(meta)
            with patch("koteguard.worktree.SESSIONS_DIR", sessions_dir):
                save_session(meta)

        with patch("koteguard.worktree.SESSIONS_DIR", sessions_dir):
            loaded = list_sessions()

        assert len(loaded) == 3


# ---------------------------------------------------------------------------
# WorktreeEngine
# ---------------------------------------------------------------------------


class TestWorktreeEngine:
    def _make_fake_repo(self, tmp_path: Path):
        """Create a minimal git repo for testing."""
        import git

        repo = git.Repo.init(tmp_path)
        # Need at least one commit
        readme = tmp_path / "README.md"
        readme.write_text("# test\n")
        repo.index.add(["README.md"])
        repo.index.commit("init")
        return repo

    def test_create_worktree(self, tmp_path):
        repo = self._make_fake_repo(tmp_path)
        worktrees_dir = tmp_path / "worktrees"
        sessions_dir = tmp_path / "sessions"

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.worktree.WORKTREES_DIR", worktrees_dir),
            patch("koteguard.worktree.load_global_config") as mock_cfg,
            patch("koteguard.worktree.append_audit"),
        ):
            mock_cfg.return_value = MagicMock(worktrees_dir=worktrees_dir)
            engine = WorktreeEngine(tmp_path)
            meta = engine.create_worktree("add auth feature", session_id="test01")

        assert meta.session_id == "test01"
        assert "kote/" in meta.branch_name
        assert Path(meta.worktree_path).exists()

        # Cleanup
        repo.git.worktree("remove", "--force", str(meta.worktree_path))
        repo.git.branch("-D", meta.branch_name)

    def test_discard_worktree(self, tmp_path):
        repo = self._make_fake_repo(tmp_path)
        worktrees_dir = tmp_path / "worktrees"
        sessions_dir = tmp_path / "sessions"

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.worktree.WORKTREES_DIR", worktrees_dir),
            patch("koteguard.worktree.load_global_config") as mock_cfg,
            patch("koteguard.worktree.append_audit"),
        ):
            mock_cfg.return_value = MagicMock(worktrees_dir=worktrees_dir)
            engine = WorktreeEngine(tmp_path)
            meta = engine.create_worktree("test task", session_id="disc01")
            ok = engine.discard_worktree("disc01")

        assert ok is True

        with patch("koteguard.worktree.SESSIONS_DIR", sessions_dir):
            loaded = load_session("disc01")
        assert loaded.status == "discarded"

    def test_discard_nonexistent_session(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        with patch("koteguard.worktree.SESSIONS_DIR", sessions_dir):
            engine = WorktreeEngine(tmp_path)
            ok = engine.discard_worktree("nonexistent-session")
        assert ok is False
