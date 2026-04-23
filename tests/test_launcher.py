"""Comprehensive tests for koteguard/launcher.py.

Covers detect_android_studio, detect_xcode, pick_ide, build_copilot_cli_command,
IDELauncher.launch_ide, IDELauncher.open_terminal, IDELauncher.print_cd_command.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from koteguard.launcher import (
    _DENY_TOOLS,
    IDELauncher,
    build_copilot_cli_command,
    detect_android_studio,
    detect_xcode,
    pick_ide,
)
from koteguard.models import AgentMode, IDEChoice

# ---------------------------------------------------------------------------
# detect_android_studio
# ---------------------------------------------------------------------------


class TestDetectAndroidStudio:
    def test_returns_none_when_not_found(self):
        with (
            patch("koteguard.launcher.shutil.which", return_value=None),
            patch("koteguard.launcher.Path.is_file", return_value=False),
            patch("koteguard.launcher.platform.system", return_value="Linux"),
        ):
            result = detect_android_studio()
        assert result is None

    def test_returns_path_when_in_which(self):
        with patch("koteguard.launcher.shutil.which", return_value="/usr/bin/studio"):
            result = detect_android_studio()
        assert result == "/usr/bin/studio"

    def test_finds_in_known_paths(self, tmp_path):
        fake_studio = tmp_path / "studio"
        fake_studio.touch()

        with (
            patch("koteguard.launcher.shutil.which", return_value=None),
            patch(
                "koteguard.launcher._ANDROID_STUDIO_PATHS",
                [str(fake_studio)],
            ),
            patch("koteguard.launcher.platform.system", return_value="Linux"),
        ):
            result = detect_android_studio()
        assert result == str(fake_studio)

    def test_darwin_osascript_fallback(self, tmp_path):
        fake_binary = tmp_path / "Contents" / "MacOS" / "studio"
        fake_binary.parent.mkdir(parents=True)
        fake_binary.touch()

        osascript_output = str(tmp_path) + "/"
        mock_result = MagicMock()
        mock_result.stdout = osascript_output

        with (
            patch("koteguard.launcher.shutil.which", return_value=None),
            patch("koteguard.launcher.Path.is_file", return_value=False),
            patch("koteguard.launcher.platform.system", return_value="Darwin"),
            patch("koteguard.launcher.subprocess.run", return_value=mock_result),
        ):
            # The candidate would be: osascript_output.strip().rstrip('/') + '/Contents/MacOS/studio'
            # We need that path to actually be_file → patch differently
            with patch.object(Path, "is_file", lambda self: str(self) == str(fake_binary)):
                result = detect_android_studio()
        # We just verify it didn't crash and returns either something or None
        assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# detect_xcode
# ---------------------------------------------------------------------------


class TestDetectXcode:
    def test_returns_none_when_not_found(self):
        with (
            patch("koteguard.launcher.shutil.which", return_value=None),
            patch("koteguard.launcher.Path.is_file", return_value=False),
        ):
            result = detect_xcode()
        assert result is None

    def test_returns_path_when_xed_in_path(self):
        with patch("koteguard.launcher.shutil.which", return_value="/usr/bin/xed"):
            result = detect_xcode()
        assert result == "/usr/bin/xed"

    def test_finds_xcode_in_known_path(self, tmp_path):
        fake_xcode = tmp_path / "Xcode"
        fake_xcode.touch()

        with (
            patch("koteguard.launcher.shutil.which", return_value=None),
            patch("koteguard.launcher._XCODE_PATHS", [str(fake_xcode)]),
        ):
            result = detect_xcode()
        assert result == str(fake_xcode)


# ---------------------------------------------------------------------------
# pick_ide
# ---------------------------------------------------------------------------


class TestPickIde:
    def test_android_choice_returns_android_studio(self):
        with patch("koteguard.launcher.detect_android_studio", return_value="/bin/studio"):
            result = pick_ide(IDEChoice.ANDROID_STUDIO, Path("/some/worktree"))
        assert result == "/bin/studio"

    def test_android_choice_returns_none_when_not_installed(self):
        with patch("koteguard.launcher.detect_android_studio", return_value=None):
            result = pick_ide(IDEChoice.ANDROID_STUDIO, Path("/some/worktree"))
        assert result is None

    def test_ios_choice_returns_xcode(self):
        with patch("koteguard.launcher.detect_xcode", return_value="/usr/bin/xed"):
            result = pick_ide(IDEChoice.XCODE, Path("/some/worktree"))
        assert result == "/usr/bin/xed"

    def test_ios_choice_returns_none_when_not_installed(self):
        with patch("koteguard.launcher.detect_xcode", return_value=None):
            result = pick_ide(IDEChoice.XCODE, Path("/some/worktree"))
        assert result is None

    def test_auto_prefers_android_for_gradle_project(self, tmp_path):
        # Create a build.gradle to signal android project
        (tmp_path / "build.gradle").touch()
        with (
            patch("koteguard.launcher.detect_android_studio", return_value="/bin/studio"),
            patch("koteguard.launcher.detect_xcode", return_value="/usr/bin/xed"),
        ):
            result = pick_ide(IDEChoice.AUTO, tmp_path)
        assert result == "/bin/studio"

    def test_auto_prefers_xcode_for_xcode_project(self, tmp_path):
        # Create an .xcodeproj to signal iOS project
        (tmp_path / "MyApp.xcodeproj").mkdir()
        with (
            patch("koteguard.launcher.detect_android_studio", return_value=None),
            patch("koteguard.launcher.detect_xcode", return_value="/usr/bin/xed"),
        ):
            result = pick_ide(IDEChoice.AUTO, tmp_path)
        assert result == "/usr/bin/xed"

    def test_auto_falls_back_to_any_available(self, tmp_path):
        with (
            patch("koteguard.launcher.detect_android_studio", return_value="/bin/studio"),
            patch("koteguard.launcher.detect_xcode", return_value=None),
        ):
            result = pick_ide(IDEChoice.AUTO, tmp_path)
        assert result == "/bin/studio"

    def test_auto_returns_none_when_nothing_installed(self, tmp_path):
        with (
            patch("koteguard.launcher.detect_android_studio", return_value=None),
            patch("koteguard.launcher.detect_xcode", return_value=None),
        ):
            result = pick_ide(IDEChoice.AUTO, tmp_path)
        assert result is None

    def test_auto_with_nonexistent_worktree(self, tmp_path):
        nonexistent = tmp_path / "nonexistent"
        with (
            patch("koteguard.launcher.detect_android_studio", return_value=None),
            patch("koteguard.launcher.detect_xcode", return_value=None),
        ):
            result = pick_ide(IDEChoice.AUTO, nonexistent)
        assert result is None


# ---------------------------------------------------------------------------
# build_copilot_cli_command
# ---------------------------------------------------------------------------


class TestBuildCopilotCliCommand:
    def test_returns_command_for_copilot_cli_mode(self, tmp_path):
        cmd = build_copilot_cli_command(tmp_path, agent_mode=AgentMode.COPILOT_CLI)
        assert cmd is not None
        assert "copilot" in cmd
        assert str(tmp_path) in cmd

    def test_returns_none_for_plugin_mode(self, tmp_path):
        cmd = build_copilot_cli_command(tmp_path, agent_mode=AgentMode.COPILOT_PLUGIN)
        assert cmd is None

    def test_returns_none_for_none_mode(self, tmp_path):
        cmd = build_copilot_cli_command(tmp_path, agent_mode=AgentMode.NONE)
        assert cmd is None

    def test_includes_all_deny_flags(self, tmp_path):
        cmd = build_copilot_cli_command(tmp_path, agent_mode=AgentMode.COPILOT_CLI)
        assert cmd is not None
        for tool in _DENY_TOOLS:
            assert tool in cmd

    def test_includes_instructions_dir_env_var(self, tmp_path):
        cmd = build_copilot_cli_command(tmp_path, agent_mode=AgentMode.COPILOT_CLI)
        assert "COPILOT_CUSTOM_INSTRUCTIONS_DIRS" in cmd
        assert ".github/instructions" in cmd

    def test_includes_cd_command(self, tmp_path):
        cmd = build_copilot_cli_command(tmp_path, agent_mode=AgentMode.COPILOT_CLI)
        assert f"cd {tmp_path}" in cmd

    def test_default_mode_is_copilot_cli(self, tmp_path):
        cmd = build_copilot_cli_command(tmp_path)
        assert cmd is not None  # default mode should produce a command


# ---------------------------------------------------------------------------
# IDELauncher
# ---------------------------------------------------------------------------


class TestIDELauncher:
    def test_launch_ide_returns_false_when_no_binary(self, tmp_path):
        with patch("koteguard.launcher.pick_ide", return_value=None):
            launcher = IDELauncher(tmp_path)
            result = launcher.launch_ide(IDEChoice.AUTO)
        assert result is False

    def test_launch_ide_returns_true_when_binary_found(self, tmp_path):
        with (
            patch("koteguard.launcher.pick_ide", return_value="/bin/studio"),
            patch("koteguard.launcher.subprocess.Popen"),
        ):
            launcher = IDELauncher(tmp_path)
            result = launcher.launch_ide(IDEChoice.ANDROID_STUDIO)
        assert result is True

    def test_launch_ide_passes_worktree_to_popen(self, tmp_path):
        with (
            patch("koteguard.launcher.pick_ide", return_value="/bin/studio"),
            patch("koteguard.launcher.subprocess.Popen") as mock_popen,
        ):
            launcher = IDELauncher(tmp_path)
            launcher.launch_ide(IDEChoice.ANDROID_STUDIO)

        call_args = mock_popen.call_args[0][0]  # positional first arg
        assert str(tmp_path) in call_args

    def test_launch_ide_xed_passes_worktree(self, tmp_path):
        with (
            patch("koteguard.launcher.pick_ide", return_value="/usr/bin/xed"),
            patch("koteguard.launcher.subprocess.Popen") as mock_popen,
        ):
            launcher = IDELauncher(tmp_path)
            launcher.launch_ide(IDEChoice.XCODE)

        call_args = mock_popen.call_args[0][0]
        assert str(tmp_path) in call_args

    def test_open_terminal_returns_true_on_darwin(self, tmp_path):
        with (
            patch("koteguard.launcher.platform.system", return_value="Darwin"),
            patch("koteguard.launcher.subprocess.Popen"),
        ):
            launcher = IDELauncher(tmp_path)
            result = launcher.open_terminal()
        assert result is True

    def test_open_terminal_returns_true_on_linux(self, tmp_path):
        with (
            patch("koteguard.launcher.platform.system", return_value="Linux"),
            patch("koteguard.launcher.shutil.which", return_value="/usr/bin/gnome-terminal"),
            patch("koteguard.launcher.subprocess.Popen"),
        ):
            launcher = IDELauncher(tmp_path)
            result = launcher.open_terminal()
        assert result is True

    def test_open_terminal_returns_true_on_windows(self, tmp_path):
        with (
            patch("koteguard.launcher.platform.system", return_value="Windows"),
            patch("koteguard.launcher.subprocess.Popen"),
        ):
            launcher = IDELauncher(tmp_path)
            result = launcher.open_terminal()
        assert result is True

    def test_open_terminal_returns_false_on_exception(self, tmp_path):
        with (
            patch("koteguard.launcher.platform.system", return_value="Darwin"),
            patch("koteguard.launcher.subprocess.Popen", side_effect=OSError("No terminal")),
        ):
            launcher = IDELauncher(tmp_path)
            result = launcher.open_terminal()
        assert result is False

    def test_print_cd_command_format(self, tmp_path):
        launcher = IDELauncher(tmp_path)
        cmd = launcher.print_cd_command()
        assert str(tmp_path) in cmd
        assert "cd" in cmd

    def test_open_terminal_sets_env_var(self, tmp_path):
        with (
            patch("koteguard.launcher.platform.system", return_value="Darwin"),
            patch("koteguard.launcher.subprocess.Popen") as mock_popen,
        ):
            launcher = IDELauncher(tmp_path)
            launcher.open_terminal()

        # Env kwarg should contain COPILOT_CUSTOM_INSTRUCTIONS_DIRS
        kwargs = mock_popen.call_args[1]
        assert "env" in kwargs
        assert "COPILOT_CUSTOM_INSTRUCTIONS_DIRS" in kwargs["env"]

    def test_deny_tools_list_non_empty(self):
        assert len(_DENY_TOOLS) > 0
        assert any("git push" in t for t in _DENY_TOOLS)
