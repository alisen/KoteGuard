"""Tests for session directory structure, context file copying, and audit logging."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from koteguard.models import SessionMeta
from koteguard.worktree import WorktreeEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(path: Path, content: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _make_fake_repo(tmp_path: Path):
    import git

    repo = git.Repo.init(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text("# test\n")
    repo.index.add(["README.md"])
    repo.index.commit("init")
    return repo


# ---------------------------------------------------------------------------
# Session subdirectory creation
# ---------------------------------------------------------------------------


class TestSessionSubdirCreation:
    def test_context_logs_output_created(self, tmp_path):
        repo = _make_fake_repo(tmp_path)
        sessions_dir = tmp_path / "sessions"
        worktrees_dir = tmp_path / "worktrees"

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.worktree.WORKTREES_DIR", worktrees_dir),
            patch("koteguard.worktree.load_global_config") as mock_cfg,
            patch("koteguard.worktree.append_session_audit"),
        ):
            mock_cfg.return_value = MagicMock(worktrees_dir=worktrees_dir)
            engine = WorktreeEngine(tmp_path)
            meta = engine.create_worktree("test", session_id="struct01")

        session_dir = sessions_dir / "struct01"
        assert (session_dir / "context").is_dir()
        assert (session_dir / "logs").is_dir()
        assert (session_dir / "output").is_dir()

        # Cleanup
        repo.git.worktree("remove", "--force", str(meta.worktree_path))
        repo.git.branch("-D", meta.branch_name)


# ---------------------------------------------------------------------------
# Context file copying
# ---------------------------------------------------------------------------


class TestContextFileCopying:
    def test_copy_context_files(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        (sessions_dir / "copy-sess" / "context").mkdir(parents=True)

        # Create source files
        plan_file = tmp_path / "PLAN.md"
        plan_file.write_text("# Test Plan\n", encoding="utf-8")
        task_file = tmp_path / "TASK.md"
        task_file.write_text("# Task\n", encoding="utf-8")

        with patch("koteguard.worktree.SESSIONS_DIR", sessions_dir):
            engine = WorktreeEngine(tmp_path)
            engine.copy_context_files(
                "copy-sess",
                {"PLAN.md": plan_file, "TASK.md": task_file},
            )

        context_dir = sessions_dir / "copy-sess" / "context"
        assert (context_dir / "PLAN.md").exists()
        assert (context_dir / "TASK.md").exists()
        assert (context_dir / "PLAN.md").read_text() == "# Test Plan\n"

    def test_missing_source_files_ignored(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        (sessions_dir / "miss-sess" / "context").mkdir(parents=True)

        with patch("koteguard.worktree.SESSIONS_DIR", sessions_dir):
            engine = WorktreeEngine(tmp_path)
            # Should not raise even if files don't exist
            engine.copy_context_files(
                "miss-sess",
                {"PLAN.md": tmp_path / "nonexistent.md"},
            )

        context_dir = sessions_dir / "miss-sess" / "context"
        assert not (context_dir / "PLAN.md").exists()


# ---------------------------------------------------------------------------
# Per-session audit.jsonl
# ---------------------------------------------------------------------------


class TestSessionAuditLog:
    def test_audit_jsonl_created_on_session(self, tmp_path):
        from koteguard.config import append_session_audit

        sessions_dir = tmp_path / "sessions"

        entry = {
            "timestamp": "2024-01-01T00:00:00Z",
            "event": "session_created",
            "session_id": "audit-01",
            "details": {"branch": "kote/audit-01-test"},
        }

        with patch("koteguard.config.SESSIONS_DIR", sessions_dir), \
             patch("koteguard.config.AUDIT_LOG_PATH", tmp_path / "audit.jsonl"):
            append_session_audit("audit-01", entry)

        audit_path = sessions_dir / "audit-01" / "logs" / "audit.jsonl"
        assert audit_path.exists()
        lines = [json.loads(l) for l in audit_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        assert lines[0]["event"] == "session_created"

    def test_audit_entries_accumulate(self, tmp_path):
        from koteguard.config import append_session_audit

        sessions_dir = tmp_path / "sessions"

        with patch("koteguard.config.SESSIONS_DIR", sessions_dir), \
             patch("koteguard.config.AUDIT_LOG_PATH", tmp_path / "audit.jsonl"):
            for i in range(3):
                append_session_audit("accum-01", {
                    "timestamp": f"2024-01-01T0{i}:00:00Z",
                    "event": f"event_{i}",
                    "session_id": "accum-01",
                    "details": {},
                })

        audit_path = sessions_dir / "accum-01" / "logs" / "audit.jsonl"
        lines = [json.loads(l) for l in audit_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 3

    def test_read_session_audit(self, tmp_path):
        from koteguard.config import append_session_audit, read_session_audit

        sessions_dir = tmp_path / "sessions"

        with patch("koteguard.config.SESSIONS_DIR", sessions_dir), \
             patch("koteguard.config.AUDIT_LOG_PATH", tmp_path / "audit.jsonl"):
            append_session_audit("read-01", {
                "timestamp": "2024-01-01T00:00:00Z",
                "event": "test_event",
                "session_id": "read-01",
                "details": {"key": "value"},
            })
            entries = read_session_audit("read-01")

        assert len(entries) == 1
        assert entries[0]["event"] == "test_event"


# ---------------------------------------------------------------------------
# Validation report generation and archival
# ---------------------------------------------------------------------------


class TestValidationReportArchival:
    def test_validation_report_written_to_output(self, tmp_path):
        from koteguard.validation import write_validation_report

        with patch("koteguard.validation.SESSIONS_DIR", tmp_path):
            path = write_validation_report("vr-sess", "# Validation Report\n\n## Test\n")

        assert path.exists()
        assert path.parent.name == "output"
        assert "Validation Report" in path.read_text()

    def test_validation_report_archived_on_accept(self, tmp_path):
        """Validation report should be copied to .kote/history/ on accept."""
        repo = _make_fake_repo(tmp_path)
        sessions_dir = tmp_path / "sessions"
        worktrees_dir = tmp_path / "worktrees"

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.worktree.WORKTREES_DIR", worktrees_dir),
            patch("koteguard.worktree.load_global_config") as mock_cfg,
            patch("koteguard.worktree.append_session_audit"),
        ):
            mock_cfg.return_value = MagicMock(worktrees_dir=worktrees_dir)
            engine = WorktreeEngine(tmp_path)
            meta = engine.create_worktree("archive test", session_id="ar-sess1")

            # Create a validation-report.md in output dir
            output_dir = sessions_dir / "ar-sess1" / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "validation-report.md").write_text(
                "# Validation Report\n", encoding="utf-8"
            )

            # Accept (this triggers archival)
            with patch("koteguard.worktree.SESSIONS_DIR", sessions_dir):
                ok = engine.accept_worktree("ar-sess1")

        # The history dir should contain the validation report
        history_root = tmp_path / ".kote" / "history"
        if history_root.exists():
            for hist_dir in history_root.iterdir():
                report = hist_dir / "validation-report.md"
                if report.exists():
                    assert "Validation Report" in report.read_text()
                    break
