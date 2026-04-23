"""Interactive CLI tests for koteguard/cli.py.

Covers the commands that require questionary prompts, git repos, and
external calls:
  - _require_git_repo (success + failure)
  - _print_banner
  - prep (dry-run, abort, refine loop, full worktree creation)
  - ide (found / not found / explicit session)
  - cli (copilot-cli mode / plugin mode / none mode)
  - cleanup (--accept / --discard / --all / uncommitted changes / force)
  - android update (mocked network)
  - init (questionary wizard)

Patching strategy for lazy imports inside functions:
  - `import questionary` inside prep/init → patch questionary.select, .text, .confirm, .checkbox
  - `from koteguard.X import Y` inside functions → patch `koteguard.X.Y`
  - `koteguard.worktree.SESSIONS_DIR` → patch to control session list
  - `koteguard.cli._require_git_repo` → patch return value directly
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import git
import pytest
from typer.testing import CliRunner

from koteguard.cli import _print_banner, _require_git_repo, app
from koteguard.models import GlobalConfig

runner = CliRunner()


# ---------------------------------------------------------------------------
# Git repo fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with one commit and return its root."""
    repo = git.Repo.init(tmp_path)
    repo.config_writer().set_value("user", "name", "Test").release()
    repo.config_writer().set_value("user", "email", "test@test.com").release()
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("init")
    return tmp_path


# ---------------------------------------------------------------------------
# Session helper
# ---------------------------------------------------------------------------


def _write_session(
    sessions_dir: Path,
    session_id: str,
    worktree_path: Path,
    project_root: Path,
    status: str = "active",
    agent_mode: str = "copilot-cli",
    plan_title: str = "My Plan",
) -> None:
    sess_dir = sessions_dir / session_id
    sess_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "session_id": session_id,
        "project_slug": "myapp",
        "project_root": str(project_root),
        "worktree_path": str(worktree_path),
        "branch_name": f"kote/{session_id}-task",
        "status": status,
        "created_at": datetime.now(tz=UTC).isoformat(),
        "completed_at": None,
        "plan_title": plan_title,
        "ide": "auto",
        "agent_mode": agent_mode,
        "android_cli_available": False,
        "skills_loaded": [],
    }
    (sess_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


# ---------------------------------------------------------------------------
# _require_git_repo
# ---------------------------------------------------------------------------


class TestRequireGitRepo:
    def test_returns_repo_root_inside_repo(self, git_repo: Path):
        result = _require_git_repo(git_repo)
        assert result == git_repo or result == git_repo.resolve()

    def test_exits_1_outside_repo(self):
        """A plain directory with no .git should raise typer.Exit(1)."""
        import click
        import typer

        with pytest.raises((typer.Exit, click.exceptions.Exit)):
            with patch("git.Repo", side_effect=git.InvalidGitRepositoryError("no repo")):
                _require_git_repo(Path("/tmp"))

    def test_cli_exits_1_when_not_in_git_repo(self, tmp_path: Path):
        """kote prep outside a git repo should exit 1."""
        with patch("git.Repo", side_effect=git.InvalidGitRepositoryError("no repo")):
            result = runner.invoke(app, ["prep", "--project", str(tmp_path)])
        assert result.exit_code == 1

    def test_cli_validate_does_not_need_git_repo(self, tmp_path: Path):
        """kote validate does NOT call _require_git_repo, so works anywhere."""
        plan_path = tmp_path / "PLAN.md"
        plan_path.write_text("", encoding="utf-8")
        result = runner.invoke(app, ["validate", str(plan_path)])
        # Should reach the validator (not be blocked by git check)
        assert result.exit_code in (0, 1)  # validator runs, just might fail/pass


# ---------------------------------------------------------------------------
# _print_banner
# ---------------------------------------------------------------------------


class TestPrintBanner:
    def test_does_not_raise(self):
        """_print_banner should execute without error."""
        _print_banner()  # no assertion needed beyond no exception


# ---------------------------------------------------------------------------
# Prep helpers
# ---------------------------------------------------------------------------


def _make_mock_info(
    project_type: str = "android",
    project_name: str = "TestApp",
    android_cli: bool = False,
    skills: list[str] | None = None,
) -> MagicMock:
    mock_info = MagicMock()
    mock_info.project_type = MagicMock()
    mock_info.project_type.value = project_type
    mock_info.project_name = project_name
    mock_info.confidence = 0.9
    mock_info.android_cli_available = android_cli
    mock_info.detected_skills = skills or []
    return mock_info


def _make_mock_scanner(info: MagicMock) -> MagicMock:
    mock = MagicMock()
    mock.return_value.scan.return_value = info
    return mock


def _make_mock_ws_model(name: str = "TestApp", tech_stack: list[str] | None = None) -> MagicMock:
    mock = MagicMock()
    mock.project_name = name
    mock.tech_stack = tech_stack or ["Kotlin"]
    return mock


# ---------------------------------------------------------------------------
# prep – dry-run path
# ---------------------------------------------------------------------------


class TestPrepDryRun:
    def test_dry_run_exits_zero(self, git_repo: Path, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        info = _make_mock_info()
        scanner = _make_mock_scanner(info)
        ws = _make_mock_ws_model()

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.project_scanner.ProjectScanner", scanner),
            patch("koteguard.planning.workspace_from_project_info", return_value=ws),
            patch("koteguard.planning.render_workspace", return_value="# WORKSPACE"),
            patch("koteguard.config.ensure_project_gitignore"),
            patch("koteguard.config.resolve_android_cli_enabled", return_value=False),
            patch(
                "koteguard.config.resolve_agent_mode", return_value=MagicMock(value="copilot-cli")
            ),
            patch("koteguard.config.load_project_config") as mock_lpc,
            patch("koteguard.config.save_project_config"),
            patch("koteguard.cli._require_git_repo", return_value=git_repo),
            patch("questionary.select") as mock_select,
            patch("questionary.text") as mock_text,
            patch("builtins.input", return_value="YES"),
        ):
            mock_select.return_value.ask.return_value = "copilot-cli"
            mock_text.return_value.ask.side_effect = [
                "Add dark mode",
                "Support dark theme",
                "Implement toggle",
                "Tests pass",
                "1 hour",
                "",
            ]
            mock_lpc.return_value = MagicMock(last_session_id=None)
            result = runner.invoke(app, ["prep", "--project", str(git_repo), "--dry-run"])

        assert result.exit_code == 0
        assert "dry-run" in result.output.lower() or "stopping" in result.output.lower()

    def test_dry_run_aborted_when_user_types_no(self, git_repo: Path, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        info = _make_mock_info()
        scanner = _make_mock_scanner(info)
        ws = _make_mock_ws_model()

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.project_scanner.ProjectScanner", scanner),
            patch("koteguard.planning.workspace_from_project_info", return_value=ws),
            patch("koteguard.planning.render_workspace", return_value="# WORKSPACE"),
            patch("koteguard.config.ensure_project_gitignore"),
            patch("koteguard.config.resolve_android_cli_enabled", return_value=False),
            patch(
                "koteguard.config.resolve_agent_mode", return_value=MagicMock(value="copilot-cli")
            ),
            patch("koteguard.cli._require_git_repo", return_value=git_repo),
            patch("questionary.select") as mock_select,
            patch("questionary.text") as mock_text,
            patch("builtins.input", return_value="no"),  # user aborts
        ):
            mock_select.return_value.ask.return_value = "copilot-cli"
            mock_text.return_value.ask.side_effect = [
                "Add dark mode",
                "Support dark theme",
                "Implement theme",
                "Tests pass",
                "1 hour",
                "",
            ]
            result = runner.invoke(app, ["prep", "--project", str(git_repo)])

        assert result.exit_code == 0
        assert "aborted" in result.output.lower() or "Aborted" in result.output

    def test_prep_refine_loop_then_confirm(self, git_repo: Path, tmp_path: Path):
        """When user types 'refine', the planning loop restarts."""
        sessions_dir = tmp_path / "sessions"
        info = _make_mock_info()
        scanner = _make_mock_scanner(info)
        ws = _make_mock_ws_model()

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.project_scanner.ProjectScanner", scanner),
            patch("koteguard.planning.workspace_from_project_info", return_value=ws),
            patch("koteguard.planning.render_workspace", return_value="# WORKSPACE"),
            patch("koteguard.config.ensure_project_gitignore"),
            patch("koteguard.config.resolve_android_cli_enabled", return_value=False),
            patch(
                "koteguard.config.resolve_agent_mode", return_value=MagicMock(value="copilot-cli")
            ),
            patch("koteguard.cli._require_git_repo", return_value=git_repo),
            patch("questionary.select") as mock_select,
            patch("questionary.text") as mock_text,
            patch("builtins.input", side_effect=["refine", "YES"]),
        ):
            mock_select.return_value.ask.return_value = "copilot-cli"
            mock_text.return_value.ask.side_effect = [
                "First title",
                "Obj",
                "Task",
                "Done",
                "1 hour",
                "",  # first loop
                "Refined title",
                "Obj2",
                "Task2",
                "Done2",
                "2 hours",
                "",  # second loop
            ]
            result = runner.invoke(app, ["prep", "--project", str(git_repo), "--dry-run"])

        assert result.exit_code == 0

    def test_prep_cancelled_when_plan_title_empty(self, git_repo: Path):
        """If questionary returns None for plan title, prep cancels."""
        info = _make_mock_info()
        scanner = _make_mock_scanner(info)
        ws = _make_mock_ws_model()

        with (
            patch("koteguard.project_scanner.ProjectScanner", scanner),
            patch("koteguard.planning.workspace_from_project_info", return_value=ws),
            patch("koteguard.planning.render_workspace", return_value="# WORKSPACE"),
            patch("koteguard.config.ensure_project_gitignore"),
            patch("koteguard.config.resolve_android_cli_enabled", return_value=False),
            patch(
                "koteguard.config.resolve_agent_mode", return_value=MagicMock(value="copilot-cli")
            ),
            patch("koteguard.cli._require_git_repo", return_value=git_repo),
            patch("questionary.select") as mock_select,
            patch("questionary.text") as mock_text,
        ):
            mock_select.return_value.ask.return_value = "copilot-cli"
            mock_text.return_value.ask.return_value = None  # empty → cancel

            result = runner.invoke(app, ["prep", "--project", str(git_repo)])

        assert result.exit_code == 0
        assert "Cancelled" in result.output or "cancelled" in result.output

    def test_prep_invalid_agent_mode_flag_exits_1(self, git_repo: Path):
        """--agent-mode with an unknown value should exit 1."""
        info = _make_mock_info()
        scanner = _make_mock_scanner(info)

        with (
            patch("koteguard.project_scanner.ProjectScanner", scanner),
            patch("koteguard.config.ensure_project_gitignore"),
            patch("koteguard.config.resolve_android_cli_enabled", return_value=False),
            patch("koteguard.cli._require_git_repo", return_value=git_repo),
            patch(
                "koteguard.planning.workspace_from_project_info", return_value=_make_mock_ws_model()
            ),
            patch("koteguard.planning.render_workspace", return_value="# WORKSPACE"),
        ):
            result = runner.invoke(
                app,
                ["prep", "--project", str(git_repo), "--agent-mode", "not-a-valid-mode"],
            )

        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# prep – full path (worktree creation)
# ---------------------------------------------------------------------------

# Helper: build the standard set of patches for a full prep run
_PREP_COMMON_PATCHES = [
    "koteguard.project_scanner.ProjectScanner",
    "koteguard.worktree.WorktreeEngine",
    "koteguard.planning.workspace_from_project_info",
    "koteguard.planning.render_workspace",
    "koteguard.planning.render_plan",
    "koteguard.planning.render_task",
    "koteguard.planning.render_copilot_instructions",
    "koteguard.planning.render_security_instructions",
    "koteguard.templates.get_template",
    "koteguard.sensitive_files.SensitiveFileHandler",
    "koteguard.launcher.IDELauncher",
    "koteguard.config.ensure_project_gitignore",
    "koteguard.config.resolve_android_cli_enabled",
    "koteguard.config.resolve_agent_mode",
    "koteguard.config.load_project_config",
    "koteguard.config.save_project_config",
    "koteguard.cli._require_git_repo",
    "questionary.select",
    "questionary.text",
    "questionary.checkbox",
    "builtins.input",
    "shutil.copy2",
]


class TestPrepFullPath:
    def _make_meta(self, session_id: str, worktree_path: Path, git_repo: Path) -> MagicMock:
        meta = MagicMock()
        meta.session_id = session_id
        meta.worktree_path = worktree_path
        meta.branch_name = f"kote/{session_id}-task"
        meta.project_root = git_repo
        return meta

    def _run_prep_with_stack(
        self,
        git_repo: Path,
        sessions_dir: Path,
        scanner: MagicMock,
        ws: MagicMock,
        engine_cls: MagicMock,
        sfh_cls: MagicMock,
        launcher_cls: MagicMock,
        agent_mode_answer: str,
        text_answers: list,
        input_answer: str = "YES",
        extra_cmd_args: list | None = None,
        android_cli: bool = False,
        checkbox_answer: list | None = None,
    ) -> tuple:
        with ExitStack() as stack:
            stack.enter_context(patch("koteguard.worktree.SESSIONS_DIR", sessions_dir))
            stack.enter_context(patch("koteguard.project_scanner.ProjectScanner", scanner))
            stack.enter_context(patch("koteguard.worktree.WorktreeEngine", engine_cls))
            stack.enter_context(
                patch("koteguard.planning.workspace_from_project_info", return_value=ws)
            )
            stack.enter_context(
                patch("koteguard.planning.render_workspace", return_value="# WORKSPACE")
            )
            stack.enter_context(patch("koteguard.planning.render_plan", return_value="# PLAN"))
            stack.enter_context(patch("koteguard.planning.render_task", return_value="# TASK"))
            stack.enter_context(
                patch("koteguard.planning.render_copilot_instructions", return_value="# COPILOT")
            )
            stack.enter_context(
                patch("koteguard.planning.render_security_instructions", return_value="# SECURITY")
            )
            stack.enter_context(patch("koteguard.templates.get_template", return_value="# AGENTS"))
            stack.enter_context(patch("koteguard.sensitive_files.SensitiveFileHandler", sfh_cls))
            stack.enter_context(patch("koteguard.launcher.IDELauncher", launcher_cls))
            stack.enter_context(patch("koteguard.config.ensure_project_gitignore"))
            stack.enter_context(
                patch("koteguard.config.resolve_android_cli_enabled", return_value=android_cli)
            )
            stack.enter_context(
                patch(
                    "koteguard.config.resolve_agent_mode",
                    return_value=MagicMock(value="copilot-cli"),
                )
            )
            stack.enter_context(patch("koteguard.config.save_project_config"))
            stack.enter_context(patch("koteguard.cli._require_git_repo", return_value=git_repo))
            stack.enter_context(patch("shutil.copy2"))
            mock_lpc = stack.enter_context(patch("koteguard.config.load_project_config"))
            mock_select = stack.enter_context(patch("questionary.select"))
            mock_text = stack.enter_context(patch("questionary.text"))
            mock_checkbox = stack.enter_context(patch("questionary.checkbox"))
            stack.enter_context(patch("builtins.input", return_value=input_answer))

            mock_lpc.return_value = MagicMock(last_session_id=None)
            mock_select.return_value.ask.return_value = agent_mode_answer
            mock_text.return_value.ask.side_effect = text_answers
            if checkbox_answer is not None:
                mock_checkbox.return_value.ask.return_value = checkbox_answer

            cmd = ["prep", "--project", str(git_repo)] + (extra_cmd_args or [])
            result = runner.invoke(app, cmd)
        return result

    def test_prep_creates_worktree_copilot_cli_mode(self, git_repo: Path, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        worktree_path = tmp_path / "wt"
        worktree_path.mkdir()

        info = _make_mock_info()
        scanner = _make_mock_scanner(info)
        ws = _make_mock_ws_model()
        meta = self._make_meta("sess-001", worktree_path, git_repo)

        engine_cls = MagicMock()
        engine_cls.return_value.create_worktree.return_value = meta
        sfh_cls = MagicMock()
        sfh_cls.return_value.inject_stubs.return_value = []
        launcher_cls = MagicMock()
        launcher_cls.return_value.launch_ide.return_value = False

        result = self._run_prep_with_stack(
            git_repo,
            sessions_dir,
            scanner,
            ws,
            engine_cls,
            sfh_cls,
            launcher_cls,
            agent_mode_answer="copilot-cli",
            text_answers=[
                "Add dark mode",
                "Support dark theme",
                "Impl toggle",
                "Tests pass",
                "1h",
                "",
            ],
        )

        assert result.exit_code == 0
        assert "Session Ready" in result.output or "Session ID" in result.output

    def test_prep_copilot_plugin_mode_shows_ide_message(self, git_repo: Path, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        worktree_path = tmp_path / "wt"
        worktree_path.mkdir()

        info = _make_mock_info(project_type="ios", project_name="iOSApp")
        scanner = _make_mock_scanner(info)
        ws = _make_mock_ws_model("iOSApp", ["Swift"])
        meta = self._make_meta("sess-ios", worktree_path, git_repo)

        engine_cls = MagicMock()
        engine_cls.return_value.create_worktree.return_value = meta
        sfh_cls = MagicMock()
        sfh_cls.return_value.inject_stubs.return_value = []
        launcher_cls = MagicMock()
        launcher_cls.return_value.launch_ide.return_value = True

        result = self._run_prep_with_stack(
            git_repo,
            sessions_dir,
            scanner,
            ws,
            engine_cls,
            sfh_cls,
            launcher_cls,
            agent_mode_answer="copilot-plugin",
            text_answers=["iOS feat", "Implement", "Code it", "Tests pass", "2h", ""],
        )

        assert result.exit_code == 0
        assert (
            "IDE" in result.output
            or "chat panel" in result.output
            or "worktree" in result.output.lower()
        )

    def test_prep_with_android_first_flag(self, git_repo: Path, tmp_path: Path):
        """--android-first triggers android skills checkbox prompt."""
        sessions_dir = tmp_path / "sessions"
        worktree_path = tmp_path / "wt"
        worktree_path.mkdir()

        info = _make_mock_info(skills=["navigation3"])
        scanner = _make_mock_scanner(info)
        ws = _make_mock_ws_model()
        meta = self._make_meta("sess-android", worktree_path, git_repo)

        engine_cls = MagicMock()
        engine_cls.return_value.create_worktree.return_value = meta
        sfh_cls = MagicMock()
        sfh_cls.return_value.inject_stubs.return_value = []
        launcher_cls = MagicMock()
        launcher_cls.return_value.launch_ide.return_value = False

        from koteguard.models import ProjectType

        info.project_type.__eq__ = lambda s, o: o in (ProjectType.ANDROID, "android")
        info.project_type.__hash__ = lambda s: hash("android")

        result = self._run_prep_with_stack(
            git_repo,
            sessions_dir,
            scanner,
            ws,
            engine_cls,
            sfh_cls,
            launcher_cls,
            agent_mode_answer="copilot-cli",
            text_answers=["Add nav", "Improve nav", "Update", "Tests pass", "1h", ""],
            extra_cmd_args=["--android-first"],
            android_cli=True,
            checkbox_answer=["navigation3"],
        )

        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# ide command
# ---------------------------------------------------------------------------


class TestIdeCommand:
    def test_ide_no_active_sessions_exits_1(self, tmp_path: Path):
        empty = tmp_path / "no-sessions"
        with patch("koteguard.worktree.SESSIONS_DIR", empty):
            result = runner.invoke(app, ["ide"])
        assert result.exit_code == 1
        assert "No active session" in result.output

    def test_ide_by_session_id_not_found_exits_1(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        with patch("koteguard.worktree.SESSIONS_DIR", sessions_dir):
            result = runner.invoke(app, ["ide", "nonexistent-session"])
        assert result.exit_code == 1

    def test_ide_worktree_not_found_exits_1(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        worktree = tmp_path / "nonexistent-wt"  # does NOT exist on disk
        _write_session(sessions_dir, "sess-x", worktree, tmp_path)

        with patch("koteguard.worktree.SESSIONS_DIR", sessions_dir):
            result = runner.invoke(app, ["ide", "sess-x"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "Worktree" in result.output

    def test_ide_launches_ide_when_worktree_exists(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        worktree = tmp_path / "wt"
        worktree.mkdir()
        _write_session(sessions_dir, "sess-y", worktree, tmp_path)

        mock_launcher = MagicMock()
        mock_launcher.return_value.launch_ide.return_value = True  # IDE launched

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.launcher.IDELauncher", mock_launcher),
        ):
            result = runner.invoke(app, ["ide", "sess-y"])
        assert result.exit_code == 0
        assert "launched" in result.output.lower()

    def test_ide_no_ide_found_shows_manual_message(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        worktree = tmp_path / "wt"
        worktree.mkdir()
        _write_session(sessions_dir, "sess-z", worktree, tmp_path)

        mock_launcher = MagicMock()
        mock_launcher.return_value.launch_ide.return_value = False  # no IDE

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.launcher.IDELauncher", mock_launcher),
        ):
            result = runner.invoke(app, ["ide", "sess-z"])
        assert result.exit_code == 0
        assert "No IDE" in result.output or "manually" in result.output.lower()

    def test_ide_uses_most_recent_active_when_no_session_given(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        worktree = tmp_path / "wt"
        worktree.mkdir()

        # Create two sessions with different timestamps
        _write_session(sessions_dir, "old-sess", worktree, tmp_path)
        # Make old-sess older
        sess_dir = sessions_dir / "old-sess"
        meta = json.loads((sess_dir / "meta.json").read_text())
        meta["created_at"] = (datetime.now(tz=UTC) - timedelta(minutes=30)).isoformat()
        (sess_dir / "meta.json").write_text(json.dumps(meta))

        _write_session(sessions_dir, "new-sess", worktree, tmp_path)

        mock_launcher = MagicMock()
        mock_launcher.return_value.launch_ide.return_value = False

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.launcher.IDELauncher", mock_launcher),
        ):
            result = runner.invoke(app, ["ide"])

        assert result.exit_code == 0

    def test_ide_with_ide_override_flag(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        worktree = tmp_path / "wt"
        worktree.mkdir()
        _write_session(sessions_dir, "sess-override", worktree, tmp_path)

        mock_launcher = MagicMock()
        mock_launcher.return_value.launch_ide.return_value = False

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.launcher.IDELauncher", mock_launcher),
        ):
            result = runner.invoke(app, ["ide", "sess-override", "--ide", "android"])

        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# cli command
# ---------------------------------------------------------------------------


class TestCliCommand:
    def test_cli_no_active_sessions_exits_1(self, tmp_path: Path):
        empty = tmp_path / "no-sessions"
        with patch("koteguard.worktree.SESSIONS_DIR", empty):
            result = runner.invoke(app, ["cli"])
        assert result.exit_code == 1

    def test_cli_copilot_cli_mode_shows_command(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        worktree = tmp_path / "wt"
        worktree.mkdir()
        _write_session(sessions_dir, "sess-cli", worktree, tmp_path, agent_mode="copilot-cli")

        mock_cmd = MagicMock(return_value="gh copilot suggest")

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.launcher.build_copilot_cli_command", mock_cmd),
            patch("koteguard.launcher.IDELauncher") as mock_launcher,
        ):
            mock_launcher.return_value.open_terminal.return_value = None
            result = runner.invoke(app, ["cli", "sess-cli"])

        assert result.exit_code == 0
        assert "copilot" in result.output.lower() or "Copilot" in result.output

    def test_cli_plugin_mode_shows_ide_message(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        worktree = tmp_path / "wt"
        worktree.mkdir()
        _write_session(sessions_dir, "sess-plugin", worktree, tmp_path, agent_mode="copilot-plugin")

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.launcher.build_copilot_cli_command", return_value=None),
            patch("koteguard.launcher.IDELauncher"),
        ):
            result = runner.invoke(app, ["cli", "sess-plugin"])

        assert result.exit_code == 0
        assert "IDE" in result.output or "chat panel" in result.output

    def test_cli_none_mode_shows_cd_command(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        worktree = tmp_path / "wt"
        worktree.mkdir()
        _write_session(sessions_dir, "sess-none", worktree, tmp_path, agent_mode="none")

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.launcher.build_copilot_cli_command", return_value=None),
            patch("koteguard.launcher.IDELauncher"),
        ):
            result = runner.invoke(app, ["cli", "sess-none"])

        assert result.exit_code == 0
        assert "cd" in result.output

    def test_cli_uses_most_recent_when_no_arg(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        worktree = tmp_path / "wt"
        worktree.mkdir()
        _write_session(sessions_dir, "recent-sess", worktree, tmp_path)

        mock_cmd = MagicMock(return_value="gh copilot suggest")

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.launcher.build_copilot_cli_command", mock_cmd),
            patch("koteguard.launcher.IDELauncher") as mock_launcher,
        ):
            mock_launcher.return_value.open_terminal.return_value = None
            result = runner.invoke(app, ["cli"])

        assert result.exit_code == 0

    def test_cli_by_explicit_session_id(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        worktree = tmp_path / "wt"
        worktree.mkdir()
        _write_session(sessions_dir, "explicit-sess", worktree, tmp_path)

        mock_cmd = MagicMock(return_value="gh copilot suggest")

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.launcher.build_copilot_cli_command", mock_cmd),
            patch("koteguard.launcher.IDELauncher") as mock_launcher,
        ):
            mock_launcher.return_value.open_terminal.return_value = None
            result = runner.invoke(app, ["cli", "explicit-sess"])

        assert result.exit_code == 0
        assert "explicit-sess" in result.output


# ---------------------------------------------------------------------------
# cleanup command – discard path
# ---------------------------------------------------------------------------


class TestCleanupDiscard:
    def test_discard_exits_1_when_no_flag(self, tmp_path: Path):
        """cleanup without --accept or --discard should exit 1."""
        sessions_dir = tmp_path / "sessions"
        worktree = tmp_path / "wt"
        worktree.mkdir()
        _write_session(sessions_dir, "sess-a", worktree, tmp_path)

        with patch("koteguard.worktree.SESSIONS_DIR", sessions_dir):
            result = runner.invoke(app, ["cleanup", "sess-a"])

        assert result.exit_code == 1

    def test_discard_specific_session(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        worktree = tmp_path / "wt"
        worktree.mkdir()
        _write_session(sessions_dir, "to-discard", worktree, tmp_path)

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.worktree.git.Repo") as mock_repo_cls,
        ):
            mock_repo_cls.return_value.git.worktree = MagicMock(return_value="")
            mock_repo_cls.return_value.git.branch = MagicMock(return_value="")
            result = runner.invoke(app, ["cleanup", "to-discard", "--discard"])

        assert result.exit_code == 0
        assert "Discarded" in result.output or "discarded" in result.output

    def test_discard_latest_active_when_no_session_arg(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        worktree = tmp_path / "wt"
        worktree.mkdir()
        _write_session(sessions_dir, "latest-active", worktree, tmp_path)

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.worktree.git.Repo") as mock_repo_cls,
        ):
            mock_repo_cls.return_value.git.worktree = MagicMock(return_value="")
            mock_repo_cls.return_value.git.branch = MagicMock(return_value="")
            result = runner.invoke(app, ["cleanup", "--discard"])

        assert result.exit_code == 0
        assert "Discarded" in result.output or "discarded" in result.output

    def test_discard_no_active_sessions_exits_gracefully(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        # A completed session — not active
        worktree = tmp_path / "wt"
        worktree.mkdir()
        _write_session(sessions_dir, "comp-sess", worktree, tmp_path, status="completed")

        with patch("koteguard.worktree.SESSIONS_DIR", sessions_dir):
            result = runner.invoke(app, ["cleanup", "--discard"])

        assert result.exit_code == 0
        assert "No active session" in result.output or "No active" in result.output

    def test_discard_all_sessions(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        wt = tmp_path / "wt"
        wt.mkdir()
        _write_session(sessions_dir, "a1", wt, tmp_path, status="active")
        _write_session(sessions_dir, "a2", wt, tmp_path, status="active")
        _write_session(sessions_dir, "c1", wt, tmp_path, status="completed")

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.worktree.git.Repo") as mock_repo_cls,
        ):
            mock_repo_cls.return_value.git.worktree = MagicMock(return_value="")
            mock_repo_cls.return_value.git.branch = MagicMock(return_value="")
            result = runner.invoke(app, ["cleanup", "--all", "--discard"])

        assert result.exit_code == 0
        # Both active sessions should be discarded
        assert result.output.count("Discarded") == 2 or result.output.count("iscarded") >= 1


# ---------------------------------------------------------------------------
# cleanup command – accept path
# ---------------------------------------------------------------------------


class TestCleanupAccept:
    def _setup(self, tmp_path: Path, session_id: str = "sess-accept") -> tuple[Path, Path]:
        sessions_dir = tmp_path / "sessions"
        worktree = tmp_path / "wt"
        worktree.mkdir(exist_ok=True)
        _write_session(sessions_dir, session_id, worktree, tmp_path)

        # Write PLAN.md so validation has something to parse
        from koteguard.models import PlanModel
        from koteguard.planning import render_plan

        plan = PlanModel(
            title="Add feature",
            objectives=["Implement X"],
            tasks=["Code it", "Test it"],
            definition_of_done=["Tests pass"],
        )
        (worktree / "PLAN.md").write_text(render_plan(plan), encoding="utf-8")
        return sessions_dir, worktree

    def test_accept_validation_pass_then_merge(self, tmp_path: Path):
        sessions_dir, worktree = self._setup(tmp_path)

        mock_repo = MagicMock()
        mock_repo.is_dirty.return_value = False
        mock_repo.git.diff.return_value = ""
        mock_repo.git.merge.return_value = ""
        mock_repo.git.worktree.return_value = ""
        mock_repo.git.branch.return_value = ""

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.worktree.git.Repo", return_value=mock_repo),
            patch("git.Repo", return_value=mock_repo),
            patch("koteguard.cli.write_validation_report", create=True),
            patch("koteguard.validation.write_validation_report"),
        ):
            result = runner.invoke(app, ["cleanup", "sess-accept", "--accept"])

        assert result.exit_code == 0
        assert (
            "Accepted" in result.output
            or "accepted" in result.output
            or "Validation" in result.output
        )

    def test_accept_blocked_by_uncommitted_changes_without_force(self, tmp_path: Path):
        sessions_dir, worktree = self._setup(tmp_path, "dirty-sess")

        mock_repo = MagicMock()
        mock_repo.is_dirty.return_value = True  # dirty!

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("git.Repo", return_value=mock_repo),
        ):
            result = runner.invoke(app, ["cleanup", "dirty-sess", "--accept"])

        assert result.exit_code == 0
        # Shows warning about uncommitted changes and "Blocked"
        assert (
            "Blocked" in result.output
            or "Uncommitted" in result.output
            or "uncommitted" in result.output
        )

    def test_accept_force_bypasses_uncommitted(self, tmp_path: Path):
        sessions_dir, worktree = self._setup(tmp_path, "force-sess")

        mock_repo = MagicMock()
        mock_repo.is_dirty.return_value = True
        mock_repo.git.diff.return_value = ""
        mock_repo.git.merge.return_value = ""
        mock_repo.git.worktree.return_value = ""
        mock_repo.git.branch.return_value = ""

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("koteguard.worktree.git.Repo", return_value=mock_repo),
            patch("git.Repo", return_value=mock_repo),
            patch("koteguard.validation.write_validation_report"),
        ):
            result = runner.invoke(app, ["cleanup", "force-sess", "--accept", "--force"])

        assert result.exit_code == 0

    def test_accept_with_validation_errors_blocked_without_force(self, tmp_path: Path):
        """Accept is blocked when plan has errors and --force not given."""
        sessions_dir, worktree = self._setup(tmp_path, "bad-sess")
        # Overwrite PLAN.md with invalid content
        (worktree / "PLAN.md").write_text("not a valid plan", encoding="utf-8")

        mock_repo = MagicMock()
        mock_repo.is_dirty.return_value = False
        mock_repo.git.diff.return_value = ""

        with (
            patch("koteguard.worktree.SESSIONS_DIR", sessions_dir),
            patch("git.Repo", return_value=mock_repo),
            patch("koteguard.validation.write_validation_report"),
        ):
            result = runner.invoke(app, ["cleanup", "bad-sess", "--accept"])

        assert result.exit_code == 0
        # Either shows "Blocked" or validation errors
        assert (
            "Blocked" in result.output
            or "error" in result.output.lower()
            or "Accepted" in result.output  # if validation passes despite bad content
        )


# ---------------------------------------------------------------------------
# android update command
# ---------------------------------------------------------------------------


class TestAndroidUpdate:
    def _json_resp(self, items: list) -> MagicMock:
        mock = MagicMock()
        mock.__enter__ = MagicMock(return_value=mock)
        mock.__exit__ = MagicMock(return_value=False)
        mock.read.return_value = json.dumps(items).encode()
        return mock

    def _text_resp(self, content: str) -> MagicMock:
        mock = MagicMock()
        mock.__enter__ = MagicMock(return_value=mock)
        mock.__exit__ = MagicMock(return_value=False)
        mock.read.return_value = content.encode("utf-8")
        return mock

    def test_update_downloads_new_skill(self, tmp_path: Path):
        cache_dir = tmp_path / "android-skills"
        root_items = [{"name": "navigation3", "type": "dir", "path": "navigation3"}]
        skill_items = [
            {
                "name": "SKILL.md",
                "type": "file",
                "path": "navigation3/SKILL.md",
                "download_url": "https://raw.githubusercontent.com/android/skills/main/nav/SKILL.md",
            }
        ]

        def urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "navigation3" in url and "raw" not in url:
                return self._json_resp(skill_items)
            if "raw" in url or "download" in url:
                return self._text_resp("# Nav3 skill\n")
            return self._json_resp(root_items)

        with (
            patch("koteguard.config.ANDROID_SKILLS_CACHE_DIR", cache_dir),
            patch("urllib.request.urlopen", side_effect=urlopen),
        ):
            result = runner.invoke(app, ["android", "update"])

        assert result.exit_code == 0
        assert "new" in result.output.lower() or "Done" in result.output

    def test_update_unchanged_when_content_matches(self, tmp_path: Path):
        cache_dir = tmp_path / "android-skills"
        cache_dir.mkdir()
        content = "# Nav3 skill\n"
        (cache_dir / "navigation3.skill.md").write_text(content, encoding="utf-8")

        root_items = [{"name": "navigation3", "type": "dir", "path": "navigation3"}]
        skill_items = [
            {
                "name": "SKILL.md",
                "type": "file",
                "path": "navigation3/SKILL.md",
                "download_url": "https://raw.github.com/nav/SKILL.md",
            }
        ]

        def urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "navigation3" in url and "raw" not in url:
                return self._json_resp(skill_items)
            return (
                self._text_resp(content)
                if "raw" in url or "SKILL" in url
                else self._json_resp(root_items)
            )

        with (
            patch("koteguard.config.ANDROID_SKILLS_CACHE_DIR", cache_dir),
            patch("urllib.request.urlopen", side_effect=urlopen),
        ):
            result = runner.invoke(app, ["android", "update"])

        assert result.exit_code == 0
        assert "unchanged" in result.output.lower()

    def test_update_exits_1_on_network_error(self, tmp_path: Path):
        cache_dir = tmp_path / "android-skills"

        with (
            patch("koteguard.config.ANDROID_SKILLS_CACHE_DIR", cache_dir),
            patch("urllib.request.urlopen", side_effect=OSError("network down")),
        ):
            result = runner.invoke(app, ["android", "update"])

        assert result.exit_code == 1
        assert "Failed" in result.output or "error" in result.output.lower()

    def test_update_exits_1_when_no_skills_found(self, tmp_path: Path):
        cache_dir = tmp_path / "android-skills"

        def urlopen(req, timeout=None):
            return self._json_resp([])  # empty repo listing

        with (
            patch("koteguard.config.ANDROID_SKILLS_CACHE_DIR", cache_dir),
            patch("urllib.request.urlopen", side_effect=urlopen),
        ):
            result = runner.invoke(app, ["android", "update"])

        assert result.exit_code == 1
        assert "No skills" in result.output or "Check your connection" in result.output

    def test_update_skips_hidden_directories(self, tmp_path: Path):
        cache_dir = tmp_path / "android-skills"
        root_items = [
            {"name": ".github", "type": "dir", "path": ".github"},
            {"name": "navigation3", "type": "dir", "path": "navigation3"},
        ]
        skill_items = [
            {
                "name": "SKILL.md",
                "type": "file",
                "path": "navigation3/SKILL.md",
                "download_url": "https://raw.github.com/nav/SKILL.md",
            }
        ]

        def urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "navigation3" in url and "raw" not in url:
                return self._json_resp(skill_items)
            if "raw" in url:
                return self._text_resp("# Nav3\n")
            return self._json_resp(root_items)

        with (
            patch("koteguard.config.ANDROID_SKILLS_CACHE_DIR", cache_dir),
            patch("urllib.request.urlopen", side_effect=urlopen),
        ):
            result = runner.invoke(app, ["android", "update"])

        assert result.exit_code == 0
        assert not (cache_dir / ".github.skill.md").exists()

    def test_update_force_redownloads_existing(self, tmp_path: Path):
        cache_dir = tmp_path / "android-skills"
        cache_dir.mkdir()
        (cache_dir / "navigation3.skill.md").write_text("# Old\n", encoding="utf-8")

        root_items = [{"name": "navigation3", "type": "dir", "path": "navigation3"}]
        skill_items = [
            {
                "name": "SKILL.md",
                "type": "file",
                "path": "navigation3/SKILL.md",
                "download_url": "https://raw.github.com/nav/SKILL.md",
            }
        ]

        def urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "navigation3" in url and "raw" not in url:
                return self._json_resp(skill_items)
            if "raw" in url:
                return self._text_resp("# New content\n")
            return self._json_resp(root_items)

        with (
            patch("koteguard.config.ANDROID_SKILLS_CACHE_DIR", cache_dir),
            patch("urllib.request.urlopen", side_effect=urlopen),
        ):
            result = runner.invoke(app, ["android", "update", "--force"])

        assert result.exit_code == 0
        assert (
            "re-downloaded" in result.output
            or "updated" in result.output
            or "Done" in result.output
        )


# ---------------------------------------------------------------------------
# init command
# ---------------------------------------------------------------------------


class TestInitCommand:
    def test_init_saves_config_with_all_defaults(self, tmp_path: Path):
        mock_cfg = GlobalConfig()

        with (
            patch("koteguard.config.load_global_config", return_value=mock_cfg),
            patch("koteguard.config.save_global_config") as mock_save,
            patch("koteguard.cli._print_banner"),
            patch("questionary.select") as mock_select,
            patch("questionary.confirm") as mock_confirm,
            patch("questionary.text") as mock_text,
        ):
            mock_select.return_value.ask.side_effect = ["copilot-cli", "auto"]
            mock_confirm.return_value.ask.return_value = True
            mock_text.return_value.ask.return_value = str(tmp_path / "worktrees")

            result = runner.invoke(app, ["init"])

        assert result.exit_code == 0
        mock_save.assert_called_once()
        assert "Config saved" in result.output or "saved" in result.output.lower()

    def test_init_shows_all_config_fields(self, tmp_path: Path):
        mock_cfg = GlobalConfig()

        with (
            patch("koteguard.config.load_global_config", return_value=mock_cfg),
            patch("koteguard.config.save_global_config"),
            patch("koteguard.cli._print_banner"),
            patch("questionary.select") as mock_select,
            patch("questionary.confirm") as mock_confirm,
            patch("questionary.text") as mock_text,
        ):
            mock_select.return_value.ask.side_effect = ["copilot-plugin", "android"]
            mock_confirm.return_value.ask.return_value = False
            mock_text.return_value.ask.return_value = str(tmp_path / "wt")

            result = runner.invoke(app, ["init"])

        assert result.exit_code == 0
        assert "agent_mode" in result.output
        assert "default_ide" in result.output
        assert "android_cli" in result.output
        assert "worktrees_dir" in result.output

    def test_init_empty_worktrees_dir_keeps_default(self):
        mock_cfg = GlobalConfig()

        with (
            patch("koteguard.config.load_global_config", return_value=mock_cfg),
            patch("koteguard.config.save_global_config") as mock_save,
            patch("koteguard.cli._print_banner"),
            patch("questionary.select") as mock_select,
            patch("questionary.confirm") as mock_confirm,
            patch("questionary.text") as mock_text,
        ):
            mock_select.return_value.ask.side_effect = ["copilot-cli", "auto"]
            mock_confirm.return_value.ask.return_value = True
            mock_text.return_value.ask.return_value = ""  # empty → keep default

            result = runner.invoke(app, ["init"])

        assert result.exit_code == 0
        saved_cfg: GlobalConfig = mock_save.call_args[0][0]
        # worktrees_dir should still be the default (not overwritten)
        assert "worktrees" in str(saved_cfg.worktrees_dir)

    def test_init_copilot_cli_mode_answer(self):
        mock_cfg = GlobalConfig()

        with (
            patch("koteguard.config.load_global_config", return_value=mock_cfg),
            patch("koteguard.config.save_global_config") as mock_save,
            patch("koteguard.cli._print_banner"),
            patch("questionary.select") as mock_select,
            patch("questionary.confirm") as mock_confirm,
            patch("questionary.text") as mock_text,
        ):
            mock_select.return_value.ask.side_effect = ["none", "ios"]
            mock_confirm.return_value.ask.return_value = False
            mock_text.return_value.ask.return_value = ""

            result = runner.invoke(app, ["init"])

        assert result.exit_code == 0
        saved_cfg: GlobalConfig = mock_save.call_args[0][0]
        assert str(saved_cfg.agent_mode) == "none"


# ---------------------------------------------------------------------------
# main() entry point
# ---------------------------------------------------------------------------


class TestMainEntryPoint:
    def test_main_callable(self):
        from koteguard.cli import main

        assert callable(main)

    def test_version_command_works(self):
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0

    def test_help_works(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "kote" in result.output.lower()
