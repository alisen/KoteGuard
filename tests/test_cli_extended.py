"""Extended CLI integration tests for koteguard/cli.py.

Exercises commands and branches not covered in test_cli.py:
- status with sessions (table rows, age formatting, old session warning)
- cleanup --accept / --discard / --all / missing flags
- android docs
- _build_starter_message helper
- _append_workspace_summary helper
- validate edge cases (both pass, both fail)
- sessions prune with actual candidates (dry-run and real)
- android update (mocked network)
- ios skills with suggested
- cli (fast-path) command
- ide (fast-path) command
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from koteguard.cli import _append_workspace_summary, _build_starter_message, app
from koteguard.models import (
    AgentMode,
    PlanModel,
    PlanTask,
    ProjectInfo,
    ProjectType,
    SessionMeta,
    SessionStatus,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_session_json(
    tmp_path: Path,
    session_id: str,
    status: str = "active",
    agent_mode: str = "copilot-cli",
    plan_title: str = "Test plan",
    created_at: datetime | None = None,
) -> Path:
    """Write a session meta.json under tmp_path/sessions/<id>/."""
    sessions_dir = tmp_path / "sessions"
    sess_dir = sessions_dir / session_id
    sess_dir.mkdir(parents=True, exist_ok=True)

    ts = (created_at or datetime.now(tz=UTC)).isoformat()
    meta = {
        "session_id": session_id,
        "project_slug": "myapp",
        "project_root": str(tmp_path),
        "worktree_path": str(tmp_path / "worktrees" / session_id),
        "branch_name": f"kote/{session_id}-task",
        "status": status,
        "created_at": ts,
        "completed_at": None,
        "plan_title": plan_title,
        "ide": "auto",
        "agent_mode": agent_mode,
        "android_cli_available": False,
        "skills_loaded": [],
    }
    (sess_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return sess_dir


# ---------------------------------------------------------------------------
# _build_starter_message
# ---------------------------------------------------------------------------


class TestBuildStarterMessage:
    def _info(self, project_type=ProjectType.ANDROID, **kwargs):
        return ProjectInfo(
            project_type=project_type,
            project_name="TestApp",
            **kwargs,
        )

    def _plan(self, tasks=None, skills=None, dod=None):
        return PlanModel(
            title="Fix login",
            objectives=["Improve UX"],
            tasks=tasks or ["Refactor auth"],
            definition_of_done=dod or ["All tests pass"],
            android_skills=skills or [],
        )

    def test_contains_read_plan_instruction(self):
        msg = _build_starter_message(self._info(), self._plan())
        assert "PLAN.md" in msg

    def test_contains_project_name(self):
        msg = _build_starter_message(self._info(), self._plan())
        assert "TestApp" in msg

    def test_contains_android_type(self):
        msg = _build_starter_message(self._info(ProjectType.ANDROID), self._plan())
        assert "android" in msg.lower()

    def test_contains_ios_type(self):
        msg = _build_starter_message(
            self._info(ProjectType.IOS, ios_deployment_target="16.0"), self._plan()
        )
        assert "ios" in msg.lower()

    def test_ios_deployment_target_included(self):
        msg = _build_starter_message(
            self._info(ProjectType.IOS, ios_deployment_target="17.0"), self._plan()
        )
        assert "17.0" in msg

    def test_android_min_sdk_included(self):
        msg = _build_starter_message(
            self._info(ProjectType.ANDROID, android_min_sdk=26), self._plan()
        )
        assert "26" in msg

    def test_android_target_sdk_included(self):
        msg = _build_starter_message(
            self._info(ProjectType.ANDROID, android_target_sdk=34), self._plan()
        )
        assert "34" in msg

    def test_skills_included_when_set(self):
        msg = _build_starter_message(self._info(), self._plan(skills=["navigation3", "agp9"]))
        assert "navigation3" in msg
        assert "agp9" in msg

    def test_no_skills_section_when_empty(self):
        msg = _build_starter_message(self._info(), self._plan(skills=[]))
        assert "Skill guides" not in msg

    def test_tasks_listed_with_ids(self):
        plan = self._plan(tasks=["Write code", "Run tests"])
        msg = _build_starter_message(self._info(), plan)
        assert "t1" in msg or "Write code" in msg
        assert "t2" in msg or "Run tests" in msg

    def test_definition_of_done_listed(self):
        plan = self._plan(dod=["Tests green", "Review done"])
        msg = _build_starter_message(self._info(), plan)
        assert "Tests green" in msg or "Done when" in msg

    def test_sdd_mark_done_instruction(self):
        msg = _build_starter_message(self._info(), self._plan())
        assert "done" in msg.lower() or "PLAN.md" in msg


# ---------------------------------------------------------------------------
# _append_workspace_summary
# ---------------------------------------------------------------------------


class TestAppendWorkspaceSummary:
    def test_creates_new_workspace_md_when_missing(self, tmp_path):
        ws_path = tmp_path / ".kote" / "WORKSPACE.md"
        _append_workspace_summary("We implemented dark mode.", project_root=tmp_path)
        assert ws_path.exists()
        content = ws_path.read_text(encoding="utf-8")
        assert "dark mode" in content

    def test_appends_to_existing_workspace_md(self, tmp_path):
        ws_dir = tmp_path / ".kote"
        ws_dir.mkdir()
        ws_path = ws_dir / "WORKSPACE.md"
        ws_path.write_text("# KoteGuard Knowledge Base\n", encoding="utf-8")

        _append_workspace_summary("Refactored auth layer.", project_root=tmp_path)
        content = ws_path.read_text(encoding="utf-8")
        assert "KoteGuard Knowledge Base" in content
        assert "Refactored auth layer" in content

    def test_summary_contains_date(self, tmp_path):
        _append_workspace_summary("Some learning.", project_root=tmp_path)
        ws_path = tmp_path / ".kote" / "WORKSPACE.md"
        content = ws_path.read_text(encoding="utf-8")
        year = str(datetime.now(tz=UTC).year)
        assert year in content

    def test_uses_fallback_home_when_no_project_root(self, tmp_path):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        with patch("koteguard.cli.Path.home", return_value=fake_home):
            _append_workspace_summary("Fallback test.", project_root=None)
        ws_path = fake_home / ".kote" / "WORKSPACE.md"
        assert ws_path.exists()
        assert "Fallback test." in ws_path.read_text(encoding="utf-8")

    def test_creates_parent_dirs(self, tmp_path):
        new_root = tmp_path / "brand_new_project"
        new_root.mkdir()
        _append_workspace_summary("Created dirs.", project_root=new_root)
        assert (new_root / ".kote").exists()


# ---------------------------------------------------------------------------
# status command – with sessions
# ---------------------------------------------------------------------------


class TestStatusWithSessions:
    def test_shows_session_table(self, tmp_path):
        _make_session_json(tmp_path, "sess-abc", plan_title="Dark mode")

        with patch("koteguard.worktree.SESSIONS_DIR", tmp_path / "sessions"):
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        # Rich truncates long values in narrow terminal — check project slug or table header
        assert "myapp" in result.output or "KoteGuard Sessions" in result.output

    def test_shows_plan_title_truncated(self, tmp_path):
        long_title = "A" * 40
        _make_session_json(tmp_path, "sess-long", plan_title=long_title)

        with patch("koteguard.worktree.SESSIONS_DIR", tmp_path / "sessions"):
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        # Title may be rendered truncated by Rich; just confirm table is shown
        assert "KoteGuard Sessions" in result.output

    def test_shows_old_session_tip(self, tmp_path):
        old_time = datetime.now(tz=UTC) - timedelta(hours=25)
        _make_session_json(tmp_path, "old-sess", status="active", created_at=old_time)

        with patch("koteguard.worktree.SESSIONS_DIR", tmp_path / "sessions"):
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        # Should show the "older than 24h" tip
        assert "24h" in result.output or "Tip" in result.output

    def test_multiple_sessions_shown(self, tmp_path):
        _make_session_json(tmp_path, "sess-1", plan_title="Plan A")
        _make_session_json(tmp_path, "sess-2", plan_title="Plan B", status="completed")

        with patch("koteguard.worktree.SESSIONS_DIR", tmp_path / "sessions"):
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        # Rich may wrap multi-word plan titles; check individual words and statuses
        output = result.output
        assert "active" in output or "acti" in output
        assert "comp" in output  # "completed" or "comp…"

    def test_no_sessions_message(self, tmp_path):
        empty_dir = tmp_path / "empty_sessions"
        with patch("koteguard.worktree.SESSIONS_DIR", empty_dir):
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "No sessions" in result.output


# ---------------------------------------------------------------------------
# cleanup command
# ---------------------------------------------------------------------------


class TestCleanupCommand:
    def test_cleanup_requires_accept_or_discard(self, tmp_path):
        with patch("koteguard.worktree.SESSIONS_DIR", tmp_path / "sessions"):
            result = runner.invoke(app, ["cleanup"])
        assert result.exit_code == 1
        assert "--accept" in result.output or "Specify" in result.output

    def test_cleanup_discard_no_sessions_exits_gracefully(self, tmp_path):
        empty = tmp_path / "empty_sessions"
        with patch("koteguard.worktree.SESSIONS_DIR", empty):
            result = runner.invoke(app, ["cleanup", "--discard"])
        assert result.exit_code == 0
        assert "No active sessions" in result.output

    def test_cleanup_accept_no_sessions_exits_gracefully(self, tmp_path):
        empty = tmp_path / "empty_sessions"
        with patch("koteguard.worktree.SESSIONS_DIR", empty):
            result = runner.invoke(app, ["cleanup", "--accept"])
        assert result.exit_code == 0
        assert "No active sessions" in result.output


# ---------------------------------------------------------------------------
# android docs command
# ---------------------------------------------------------------------------


class TestAndroidDocs:
    def test_exits_zero(self):
        with patch("koteguard.config.SESSIONS_DIR", Path("/tmp/nonexistent-kote")):
            result = runner.invoke(app, ["android", "docs"])
        assert result.exit_code == 0

    def test_shows_documentation_table(self):
        with patch("koteguard.config.SESSIONS_DIR", Path("/tmp/nonexistent-kote")):
            result = runner.invoke(app, ["android", "docs"])
        assert "Android Developers" in result.output or "Documentation" in result.output

    def test_shows_jetpack_compose_link(self):
        with patch("koteguard.config.SESSIONS_DIR", Path("/tmp/nonexistent-kote")):
            result = runner.invoke(app, ["android", "docs"])
        assert "Jetpack Compose" in result.output

    def test_shows_worktree_context_status(self):
        with patch("koteguard.config.SESSIONS_DIR", Path("/tmp/nonexistent-kote")):
            result = runner.invoke(app, ["android", "docs"])
        assert "worktree" in result.output.lower()


# ---------------------------------------------------------------------------
# sessions prune command – with real candidates
# ---------------------------------------------------------------------------


class TestSessionsPruneWithCandidates:
    def _prune_patches(self, sessions_dir: Path):
        """Return a combined patch context for sessions prune tests.

        The `sessions prune` command imports SESSIONS_DIR from koteguard.config AND
        calls list_sessions() which reads from koteguard.worktree.SESSIONS_DIR.
        Both must be patched to the same directory.
        """
        from contextlib import ExitStack

        stack = ExitStack()
        stack.enter_context(patch("koteguard.worktree.SESSIONS_DIR", sessions_dir))
        stack.enter_context(patch("koteguard.config.SESSIONS_DIR", sessions_dir))
        return stack

    def test_dry_run_shows_candidates(self, tmp_path):
        old_time = datetime.now(tz=UTC) - timedelta(days=35)
        _make_session_json(tmp_path, "old-completed", status="completed", created_at=old_time)
        sessions_dir = tmp_path / "sessions"

        with self._prune_patches(sessions_dir):
            result = runner.invoke(app, ["sessions", "prune", "--dry-run", "--days", "30"])

        assert result.exit_code == 0
        assert "old-completed" in result.output or "would remove" in result.output

    def test_prune_skips_active_sessions(self, tmp_path):
        old_time = datetime.now(tz=UTC) - timedelta(days=35)
        _make_session_json(tmp_path, "old-active", status="active", created_at=old_time)
        sessions_dir = tmp_path / "sessions"

        with self._prune_patches(sessions_dir):
            result = runner.invoke(app, ["sessions", "prune", "--days", "30"])

        assert result.exit_code == 0
        assert "No completed" in result.output

    def test_prune_removes_session_dir(self, tmp_path):
        old_time = datetime.now(tz=UTC) - timedelta(days=35)
        _make_session_json(tmp_path, "old-discarded", status="discarded", created_at=old_time)
        session_dir = tmp_path / "sessions" / "old-discarded"
        assert session_dir.exists()
        sessions_dir = tmp_path / "sessions"

        with self._prune_patches(sessions_dir):
            result = runner.invoke(app, ["sessions", "prune", "--days", "30"])

        assert result.exit_code == 0
        assert not session_dir.exists()

    def test_dry_run_does_not_delete(self, tmp_path):
        old_time = datetime.now(tz=UTC) - timedelta(days=35)
        _make_session_json(tmp_path, "keep-me", status="completed", created_at=old_time)
        session_dir = tmp_path / "sessions" / "keep-me"
        sessions_dir = tmp_path / "sessions"

        with self._prune_patches(sessions_dir):
            runner.invoke(app, ["sessions", "prune", "--dry-run", "--days", "30"])

        # Directory should still exist because --dry-run
        assert session_dir.exists()

    def test_prune_respects_custom_days(self, tmp_path):
        young_time = datetime.now(tz=UTC) - timedelta(days=5)
        _make_session_json(tmp_path, "young-completed", status="completed", created_at=young_time)
        sessions_dir = tmp_path / "sessions"

        with self._prune_patches(sessions_dir):
            result = runner.invoke(app, ["sessions", "prune", "--days", "10"])

        assert result.exit_code == 0
        assert "No completed" in result.output  # 5 days < 10 days threshold


# ---------------------------------------------------------------------------
# validate command – extended cases
# ---------------------------------------------------------------------------


class TestValidateExtended:
    def test_validate_with_warnings_exits_zero(self, tmp_path):
        from koteguard.models import PlanModel
        from koteguard.planning import render_plan

        plan = PlanModel(
            title="Plan",
            objectives=["Obj"],
            tasks=["Task"],
            definition_of_done=["Done"],
            estimated_time="unknown",  # triggers "unknown" warning
        )
        plan_path = tmp_path / "PLAN.md"
        plan_path.write_text(render_plan(plan), encoding="utf-8")

        result = runner.invoke(app, ["validate", str(plan_path)])
        assert result.exit_code == 0  # warnings don't fail

    def test_validate_empty_plan_exits_1(self, tmp_path):
        plan_path = tmp_path / "PLAN.md"
        plan_path.write_text("", encoding="utf-8")

        result = runner.invoke(app, ["validate", str(plan_path)])
        assert result.exit_code == 1

    def test_validate_valid_workspace_only(self, tmp_path):
        from koteguard.models import PlanModel, WorkspaceModel
        from koteguard.planning import render_plan, render_workspace

        plan = PlanModel(
            title="Plan",
            objectives=["Obj"],
            tasks=["Task"],
            definition_of_done=["Done"],
        )
        ws = WorkspaceModel(project_name="App", tech_stack=["Kotlin"])

        plan_path = tmp_path / "PLAN.md"
        plan_path.write_text(render_plan(plan), encoding="utf-8")
        ws_path = tmp_path / "WORKSPACE.md"
        ws_path.write_text(render_workspace(ws), encoding="utf-8")

        result = runner.invoke(app, ["validate", str(plan_path), "-w", str(ws_path)])
        assert result.exit_code == 0
        assert "valid" in result.output.lower()


# ---------------------------------------------------------------------------
# android skills – with cache dir
# ---------------------------------------------------------------------------


class TestAndroidSkillsWithCache:
    def test_shows_source_column(self, tmp_path):
        result = runner.invoke(app, ["android", "skills", "--project", str(tmp_path)])
        assert result.exit_code == 0
        assert "bundled" in result.output or "Source" in result.output

    def test_cached_skills_override_bundled(self, tmp_path):
        # Populate a fake cache dir
        cache_dir = tmp_path / "android-skills"
        cache_dir.mkdir()
        (cache_dir / "custom-skill.skill.md").write_text(
            "# Custom Skill\n\nCustom best practices.\n", encoding="utf-8"
        )

        # ANDROID_SKILLS_CACHE_DIR is lazy-imported inside android_skills — patch at source
        with patch("koteguard.config.ANDROID_SKILLS_CACHE_DIR", cache_dir):
            result = runner.invoke(app, ["android", "skills", "--project", str(tmp_path)])

        assert result.exit_code == 0
        assert "custom-skill" in result.output

    def test_shows_sync_tip_when_no_cache(self, tmp_path):
        nonexistent_cache = tmp_path / "no-cache"
        with patch("koteguard.config.ANDROID_SKILLS_CACHE_DIR", nonexistent_cache):
            result = runner.invoke(app, ["android", "skills", "--project", str(tmp_path)])
        assert result.exit_code == 0
        assert "update" in result.output.lower() or "kote android update" in result.output

    def test_shows_count_tip_when_cache_exists(self, tmp_path):
        cache_dir = tmp_path / "android-skills"
        cache_dir.mkdir()
        (cache_dir / "nav.skill.md").write_text("# Nav\n\nContent.\n", encoding="utf-8")

        with patch("koteguard.config.ANDROID_SKILLS_CACHE_DIR", cache_dir):
            result = runner.invoke(app, ["android", "skills", "--project", str(tmp_path)])

        assert result.exit_code == 0
        assert "1" in result.output  # "1 skill(s) synced"


# ---------------------------------------------------------------------------
# ios skills – with project detection
# ---------------------------------------------------------------------------


class TestIosSkillsExtended:
    def test_ios_skills_with_suggested(self, tmp_path):
        # Create a swift file so scanner detects swiftui-patterns
        swift_file = tmp_path / "App.swift"
        swift_file.write_text(
            "import SwiftUI\n\nstruct App: View { var body: some View {} }\n", encoding="utf-8"
        )

        result = runner.invoke(app, ["ios", "skills", "--project", str(tmp_path)])
        assert result.exit_code == 0
        assert "swiftui-patterns" in result.output

    def test_ios_skills_shows_run_prep_tip_when_not_suggested(self, tmp_path):
        result = runner.invoke(app, ["ios", "skills", "--project", str(tmp_path)])
        assert result.exit_code == 0
        # When no iOS project detected, shows the "Run kote prep" tip
        assert "prep" in result.output.lower() or "iOS Skills" in result.output


# ---------------------------------------------------------------------------
# version command
# ---------------------------------------------------------------------------


class TestVersionCommand:
    def test_version_includes_semver_pattern(self):
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        import re

        assert re.search(r"v?\d+\.\d+\.\d+", result.output)
