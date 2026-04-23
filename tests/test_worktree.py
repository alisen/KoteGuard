"""Comprehensive tests for koteguard/worktree.py.

Covers _slugify, _session_meta_path, load_session, save_session, list_sessions,
WorktreeEngine.create_worktree, accept_worktree, discard_worktree, copy_context_files,
_archive_accept, _archive_discard, _create_session_dirs, _history_dir.

Git operations are mocked via unittest.mock so the tests don't require a real git repo.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from koteguard.models import AgentMode, SessionMeta, SessionStatus

# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_lowercase(self):
        from koteguard.worktree import _slugify

        assert _slugify("MyApp") == "myapp"

    def test_spaces_to_hyphens(self):
        from koteguard.worktree import _slugify

        assert _slugify("my cool project") == "my-cool-project"

    def test_special_chars_removed(self):
        from koteguard.worktree import _slugify

        assert _slugify("my@project!") == "my-project"

    def test_leading_trailing_hyphens_stripped(self):
        from koteguard.worktree import _slugify

        assert not _slugify("  ---abc---  ").startswith("-")

    def test_max_40_chars(self):
        from koteguard.worktree import _slugify

        long_input = "a" * 100
        result = _slugify(long_input)
        assert len(result) <= 40

    def test_empty_string_returns_project(self):
        from koteguard.worktree import _slugify

        assert _slugify("") == "project"

    def test_only_specials_returns_project(self):
        from koteguard.worktree import _slugify

        assert _slugify("@@@") == "project"

    def test_numbers_preserved(self):
        from koteguard.worktree import _slugify

        assert _slugify("project123") == "project123"


# ---------------------------------------------------------------------------
# _session_meta_path
# ---------------------------------------------------------------------------


class TestSessionMetaPath:
    def test_path_structure(self, tmp_path):
        with patch("koteguard.worktree.SESSIONS_DIR", tmp_path):
            from koteguard.worktree import _session_meta_path

            path = _session_meta_path("sess-abc")
        assert path == tmp_path / "sess-abc" / "meta.json"


# ---------------------------------------------------------------------------
# save_session / load_session
# ---------------------------------------------------------------------------


class TestSaveLoadSession:
    def _make_meta(self, tmp_path, session_id="sess-001") -> SessionMeta:
        return SessionMeta(
            session_id=session_id,
            project_slug="myapp",
            project_root=tmp_path,
            worktree_path=tmp_path / "wt",
            branch_name=f"kote/{session_id}-task",
        )

    def test_save_creates_meta_json(self, tmp_path):
        with patch("koteguard.worktree.SESSIONS_DIR", tmp_path):
            from koteguard.worktree import save_session

            meta = self._make_meta(tmp_path)
            save_session(meta)
            assert (tmp_path / "sess-001" / "meta.json").exists()

    def test_load_returns_session_meta(self, tmp_path):
        with patch("koteguard.worktree.SESSIONS_DIR", tmp_path):
            from koteguard.worktree import load_session, save_session

            meta = self._make_meta(tmp_path)
            save_session(meta)
            loaded = load_session("sess-001")

        assert loaded is not None
        assert loaded.session_id == "sess-001"
        assert loaded.project_slug == "myapp"

    def test_load_returns_none_for_missing(self, tmp_path):
        with patch("koteguard.worktree.SESSIONS_DIR", tmp_path):
            from koteguard.worktree import load_session

            result = load_session("nonexistent-session")
        assert result is None

    def test_save_preserves_status(self, tmp_path):
        with patch("koteguard.worktree.SESSIONS_DIR", tmp_path):
            from koteguard.worktree import load_session, save_session

            meta = self._make_meta(tmp_path)
            meta.status = SessionStatus.COMPLETED
            save_session(meta)
            loaded = load_session("sess-001")

        assert loaded.status == "completed"

    def test_save_preserves_agent_mode(self, tmp_path):
        with patch("koteguard.worktree.SESSIONS_DIR", tmp_path):
            from koteguard.worktree import load_session, save_session

            meta = self._make_meta(tmp_path)
            meta.agent_mode = AgentMode.COPILOT_PLUGIN
            save_session(meta)
            loaded = load_session("sess-001")

        assert loaded.agent_mode == "copilot-plugin"

    def test_save_preserves_plan_title(self, tmp_path):
        with patch("koteguard.worktree.SESSIONS_DIR", tmp_path):
            from koteguard.worktree import load_session, save_session

            meta = self._make_meta(tmp_path)
            meta.plan_title = "My Feature"
            save_session(meta)
            loaded = load_session("sess-001")

        assert loaded.plan_title == "My Feature"


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------


class TestListSessions:
    def _make_session_dir(self, sessions_dir: Path, session_id: str, **kwargs) -> None:
        sess_dir = sessions_dir / session_id
        sess_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "session_id": session_id,
            "project_slug": "myapp",
            "project_root": str(sessions_dir.parent),
            "worktree_path": str(sessions_dir.parent / "wt"),
            "branch_name": f"kote/{session_id}",
            "status": "active",
            "created_at": kwargs.get("created_at", datetime.now(tz=UTC).isoformat()),
            "plan_title": kwargs.get("plan_title", ""),
            "ide": "auto",
            "agent_mode": "copilot-cli",
            "android_cli_available": False,
            "skills_loaded": [],
            "completed_at": None,
        }
        (sess_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    def test_empty_when_no_sessions_dir(self, tmp_path):
        nonexistent = tmp_path / "no-sessions"
        with patch("koteguard.worktree.SESSIONS_DIR", nonexistent):
            from koteguard.worktree import list_sessions

            result = list_sessions()
        assert result == []

    def test_returns_all_sessions(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        self._make_session_dir(sessions_dir, "sess-001")
        self._make_session_dir(sessions_dir, "sess-002")

        with patch("koteguard.worktree.SESSIONS_DIR", sessions_dir):
            from koteguard.worktree import list_sessions

            result = list_sessions()
        assert len(result) == 2

    def test_sorted_by_created_at_ascending(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        older = (datetime.now(tz=UTC) - timedelta(hours=2)).isoformat()
        newer = datetime.now(tz=UTC).isoformat()
        self._make_session_dir(sessions_dir, "newer-sess", created_at=newer)
        self._make_session_dir(sessions_dir, "older-sess", created_at=older)

        with patch("koteguard.worktree.SESSIONS_DIR", sessions_dir):
            from koteguard.worktree import list_sessions

            result = list_sessions()
        assert result[0].session_id == "older-sess"
        assert result[1].session_id == "newer-sess"

    def test_skips_dirs_without_meta_json(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        self._make_session_dir(sessions_dir, "valid-sess")
        (sessions_dir / "orphan-dir").mkdir()  # no meta.json

        with patch("koteguard.worktree.SESSIONS_DIR", sessions_dir):
            from koteguard.worktree import list_sessions

            result = list_sessions()
        assert len(result) == 1

    def test_skips_corrupt_meta_json(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        self._make_session_dir(sessions_dir, "valid-sess")
        corrupt_dir = sessions_dir / "corrupt-sess"
        corrupt_dir.mkdir()
        (corrupt_dir / "meta.json").write_text("NOT JSON", encoding="utf-8")

        with patch("koteguard.worktree.SESSIONS_DIR", sessions_dir):
            from koteguard.worktree import list_sessions

            result = list_sessions()
        assert len(result) == 1


# ---------------------------------------------------------------------------
# WorktreeEngine
# ---------------------------------------------------------------------------


def _make_mock_repo(tmp_path: Path, branch_name: str = "main"):
    """Build a mock git.Repo suitable for patching."""
    mock_repo = MagicMock()
    mock_repo.working_tree_dir = str(tmp_path)
    mock_repo.head.is_detached = False
    mock_repo.active_branch.name = branch_name
    mock_repo.git.worktree = MagicMock(return_value="")
    mock_repo.git.merge = MagicMock(return_value="")
    mock_repo.git.diff = MagicMock(return_value="diff content")
    mock_repo.git.branch = MagicMock(return_value="")
    mock_repo.git.worktree = MagicMock(return_value="")
    mock_repo.is_dirty = MagicMock(return_value=False)
    return mock_repo


class TestWorktreeEngineCreate:
    def test_create_worktree_returns_session_meta(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        mock_repo = _make_mock_repo(tmp_path)

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.worktree.git.Repo", return_value=mock_repo),
            patch("koteguard.worktree.load_global_config") as mock_cfg,
            patch("koteguard.worktree.append_session_audit"),
        ):
            from koteguard.models import GlobalConfig
            from koteguard.worktree import WorktreeEngine

            mock_cfg.return_value = GlobalConfig(
                worktrees_dir=tmp_path / "worktrees",
            )
            engine = WorktreeEngine(tmp_path)
            meta = engine.create_worktree(
                task_description="add feature",
                plan_title="Add dark mode",
            )

        assert meta.session_id is not None
        assert "kote/" in meta.branch_name
        assert meta.status == "active"
        assert meta.plan_title == "Add dark mode"

    def test_create_worktree_uses_custom_session_id(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        mock_repo = _make_mock_repo(tmp_path)

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.worktree.git.Repo", return_value=mock_repo),
            patch("koteguard.worktree.load_global_config") as mock_cfg,
            patch("koteguard.worktree.append_session_audit"),
        ):
            from koteguard.models import GlobalConfig
            from koteguard.worktree import WorktreeEngine

            mock_cfg.return_value = GlobalConfig(worktrees_dir=tmp_path / "worktrees")
            engine = WorktreeEngine(tmp_path)
            meta = engine.create_worktree(session_id="custom-id", task_description="task")

        assert meta.session_id == "custom-id"

    def test_create_worktree_creates_session_dirs(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        mock_repo = _make_mock_repo(tmp_path)

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.worktree.git.Repo", return_value=mock_repo),
            patch("koteguard.worktree.load_global_config") as mock_cfg,
            patch("koteguard.worktree.append_session_audit"),
        ):
            from koteguard.models import GlobalConfig
            from koteguard.worktree import WorktreeEngine

            mock_cfg.return_value = GlobalConfig(worktrees_dir=tmp_path / "worktrees")
            engine = WorktreeEngine(tmp_path)
            engine.create_worktree(session_id="test-sess", task_description="task")

        sess_base = sessions_dir / "test-sess"
        assert (sess_base / "context").exists()
        assert (sess_base / "logs").exists()
        assert (sess_base / "output").exists()

    def test_create_worktree_detached_head_uses_HEAD(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        mock_repo = _make_mock_repo(tmp_path)
        mock_repo.head.is_detached = True

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.worktree.git.Repo", return_value=mock_repo),
            patch("koteguard.worktree.load_global_config") as mock_cfg,
            patch("koteguard.worktree.append_session_audit"),
        ):
            from koteguard.models import GlobalConfig
            from koteguard.worktree import WorktreeEngine

            mock_cfg.return_value = GlobalConfig(worktrees_dir=tmp_path / "worktrees")
            engine = WorktreeEngine(tmp_path)
            engine.create_worktree(session_id="det-sess", task_description="task")

        # Verify worktree add was called with HEAD
        call_args = mock_repo.git.worktree.call_args
        assert call_args[0][-1] == "HEAD"


class TestWorktreeEngineAcceptDiscard:
    def _create_saved_session(
        self, tmp_path: Path, sessions_dir: Path, session_id: str
    ) -> SessionMeta:
        """Create and save a session meta for testing accept/discard."""
        meta = SessionMeta(
            session_id=session_id,
            project_slug="myapp",
            project_root=tmp_path,
            worktree_path=tmp_path / "wt",
            branch_name=f"kote/{session_id}-task",
            status=SessionStatus.ACTIVE,
        )
        sess_dir = sessions_dir / session_id
        sess_dir.mkdir(parents=True, exist_ok=True)
        for subdir in ("context", "logs", "output"):
            (sess_dir / subdir).mkdir(parents=True, exist_ok=True)
        (sess_dir / "meta.json").write_text(
            json.dumps(meta.model_dump(mode="json"), default=str), encoding="utf-8"
        )
        return meta

    def test_accept_returns_false_for_missing_session(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        with patch("koteguard.worktree.SESSIONS_DIR", sessions_dir):
            from koteguard.worktree import WorktreeEngine

            engine = WorktreeEngine(tmp_path)
            result = engine.accept_worktree("nonexistent")

        assert result is False

    def test_discard_returns_false_for_missing_session(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        with patch("koteguard.worktree.SESSIONS_DIR", sessions_dir):
            from koteguard.worktree import WorktreeEngine

            engine = WorktreeEngine(tmp_path)
            result = engine.discard_worktree("nonexistent")

        assert result is False

    def test_accept_worktree_marks_completed(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        self._create_saved_session(tmp_path, sessions_dir, "sess-accept")
        mock_repo = _make_mock_repo(tmp_path)

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.worktree.git.Repo", return_value=mock_repo),
            patch("koteguard.worktree.append_session_audit"),
        ):
            from koteguard.worktree import WorktreeEngine, load_session

            engine = WorktreeEngine(tmp_path)
            result = engine.accept_worktree("sess-accept")
            saved = load_session("sess-accept")

        assert result is True
        assert saved.status == "completed"
        assert saved.completed_at is not None

    def test_discard_worktree_marks_discarded(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        self._create_saved_session(tmp_path, sessions_dir, "sess-discard")
        mock_repo = _make_mock_repo(tmp_path)

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.worktree.git.Repo", return_value=mock_repo),
            patch("koteguard.worktree.append_session_audit"),
        ):
            from koteguard.worktree import WorktreeEngine, load_session

            engine = WorktreeEngine(tmp_path)
            result = engine.discard_worktree("sess-discard")
            saved = load_session("sess-discard")

        assert result is True
        assert saved.status == "discarded"


class TestWorktreeCopyContextFiles:
    def test_copies_existing_files(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        src_file = tmp_path / "PLAN.md"
        src_file.write_text("# Plan", encoding="utf-8")

        with patch("koteguard.worktree.SESSIONS_DIR", sessions_dir):
            from koteguard.worktree import WorktreeEngine

            engine = WorktreeEngine(tmp_path)
            engine.copy_context_files("my-sess", {"PLAN.md": src_file})

        dest = sessions_dir / "my-sess" / "context" / "PLAN.md"
        assert dest.exists()
        assert dest.read_text(encoding="utf-8") == "# Plan"

    def test_skips_missing_source_files(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        missing = tmp_path / "nonexistent.md"

        with patch("koteguard.worktree.SESSIONS_DIR", sessions_dir):
            from koteguard.worktree import WorktreeEngine

            engine = WorktreeEngine(tmp_path)
            engine.copy_context_files("my-sess", {"PLAN.md": missing})

        dest = sessions_dir / "my-sess" / "context" / "PLAN.md"
        assert not dest.exists()


class TestWorktreeHistoryDir:
    def test_history_dir_in_kote_dir(self, tmp_path):
        with patch("koteguard.worktree.SESSIONS_DIR", tmp_path / "sessions"):
            from koteguard.worktree import WorktreeEngine

            engine = WorktreeEngine(tmp_path)
            history_dir = engine._history_dir(tmp_path, "sess-abc")

        assert ".kote" in str(history_dir)
        assert "history" in str(history_dir)
        assert "sess-abc" in str(history_dir)
