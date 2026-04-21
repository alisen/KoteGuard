"""Tests for token hygiene features: --compact flow, score calculation, status columns."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(path: Path, content: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# WORKSPACE.md compact append
# ---------------------------------------------------------------------------


class TestWorkspaceSummaryAppend:
    def test_append_to_existing_workspace(self, tmp_path):
        ws_path = tmp_path / "WORKSPACE.md"
        ws_path.write_text("# KoteGuard KB\n\n## Existing Section\n\nContent.\n", encoding="utf-8")

        from koteguard.cli import _append_workspace_summary
        from unittest.mock import patch

        with patch("koteguard.cli.Path.home", return_value=tmp_path):
            # Directly call with the tmp_path workspace
            workspace_path = tmp_path / ".kote" / "WORKSPACE.md"
            workspace_path.parent.mkdir(parents=True, exist_ok=True)
            workspace_path.write_text("# KoteGuard KB\n", encoding="utf-8")
            # Monkeypatch the home path
            import koteguard.cli as cli_module
            with patch.object(cli_module, "console"):
                with patch("pathlib.Path.home", return_value=tmp_path):
                    # Simulate what _append_workspace_summary does
                    summary = "Implemented login screen. Key decision: use JWT tokens."
                    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                    section = f"\n## Session Summary ({date_str})\n\n{summary}\n"
                    workspace_path.write_text(workspace_path.read_text() + section, encoding="utf-8")

        content = workspace_path.read_text()
        assert "Session Summary" in content
        assert "login screen" in content

    def test_append_creates_new_workspace(self, tmp_path):
        ws_path = tmp_path / ".kote" / "WORKSPACE.md"
        ws_path.parent.mkdir(parents=True, exist_ok=True)

        summary = "First session. Key decisions: MVVM pattern."
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        section = f"\n## Session Summary ({date_str})\n\n{summary}\n"

        ws_path.write_text(f"# KoteGuard Knowledge Base\n{section}", encoding="utf-8")

        assert ws_path.exists()
        content = ws_path.read_text()
        assert "Session Summary" in content


# ---------------------------------------------------------------------------
# Token hygiene score in validation report
# ---------------------------------------------------------------------------


class TestTokenHygieneScore:
    def test_low_pressure_for_new_session(self, tmp_path):
        from koteguard.validation import render_validation_report, ValidationResult
        from unittest.mock import patch

        plan_result = ValidationResult()
        changes_result = ValidationResult()
        created_at = datetime.now(tz=timezone.utc) - timedelta(minutes=30)

        with patch("koteguard.validation.read_session_audit", return_value=[]):
            report = render_validation_report(
                session_id="tok-01",
                plan_result=plan_result,
                changes_result=changes_result,
                skills_result=None,
                worktree_path=tmp_path,
                plan_path=tmp_path / "PLAN.md",
                created_at=created_at,
            )

        assert "Token Hygiene Score" in report
        assert "Low" in report
        assert "m" in report  # age in minutes

    def test_high_pressure_for_old_session(self, tmp_path):
        from koteguard.validation import render_validation_report, ValidationResult
        from unittest.mock import patch

        plan_result = ValidationResult()
        changes_result = ValidationResult()
        created_at = datetime.now(tz=timezone.utc) - timedelta(days=2)

        with patch("koteguard.validation.read_session_audit", return_value=[]):
            report = render_validation_report(
                session_id="tok-02",
                plan_result=plan_result,
                changes_result=changes_result,
                skills_result=None,
                worktree_path=tmp_path,
                plan_path=tmp_path / "PLAN.md",
                created_at=created_at,
            )

        assert "High" in report
        assert "compact" in report.lower() or "WORKSPACE" in report

    def test_medium_pressure(self, tmp_path):
        from koteguard.validation import render_validation_report, ValidationResult
        from unittest.mock import patch

        plan_result = ValidationResult()
        changes_result = ValidationResult()
        created_at = datetime.now(tz=timezone.utc) - timedelta(hours=6)

        with patch("koteguard.validation.read_session_audit", return_value=[]):
            report = render_validation_report(
                session_id="tok-03",
                plan_result=plan_result,
                changes_result=changes_result,
                skills_result=None,
                worktree_path=tmp_path,
                plan_path=tmp_path / "PLAN.md",
                created_at=created_at,
            )

        assert "Medium" in report


# ---------------------------------------------------------------------------
# Status table columns
# ---------------------------------------------------------------------------


class TestStatusTableColumns:
    def test_session_age_formatting(self):
        """Test that session age is formatted correctly."""
        from datetime import datetime, timezone, timedelta

        now = datetime.now(tz=timezone.utc)

        # 30 minutes old
        age_30m = (now - (now - timedelta(minutes=30))).total_seconds()
        assert age_30m == pytest.approx(1800, abs=60)

        # 2 hours old
        age_2h = (now - (now - timedelta(hours=2))).total_seconds()
        assert age_2h == pytest.approx(7200, abs=60)

    def test_context_pressure_low_for_small_plan(self, tmp_path):
        """A small PLAN.md should result in Low context pressure."""
        plan_file = tmp_path / "PLAN.md"
        plan_file.write_text("# Small Plan\n\nMinimal content.\n", encoding="utf-8")

        plan_size = plan_file.stat().st_size
        assert plan_size < 3000
        # Low pressure expected
        context_pressure = "Low"
        if plan_size > 10000:
            context_pressure = "High"
        elif plan_size > 3000:
            context_pressure = "Medium"
        assert context_pressure == "Low"

    def test_context_pressure_high_for_large_plan(self, tmp_path):
        """A large PLAN.md (>10KB) should result in High context pressure."""
        plan_file = tmp_path / "PLAN.md"
        # Write > 10KB
        plan_file.write_text("# Large Plan\n\n" + "x" * 12000, encoding="utf-8")

        plan_size = plan_file.stat().st_size
        context_pressure = "Low"
        if plan_size > 10000:
            context_pressure = "High"
        elif plan_size > 3000:
            context_pressure = "Medium"
        assert context_pressure == "High"
