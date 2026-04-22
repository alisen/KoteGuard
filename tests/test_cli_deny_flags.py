"""Tests for Copilot CLI deny flags and COPILOT_CUSTOM_INSTRUCTIONS_DIRS."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from koteguard.launcher import build_copilot_cli_command, _DENY_TOOLS
from koteguard.models import AgentMode


# ---------------------------------------------------------------------------
# build_copilot_cli_command
# ---------------------------------------------------------------------------


class TestBuildCopilotCliCommand:
    def test_returns_none_for_plugin_mode(self, tmp_path):
        result = build_copilot_cli_command(tmp_path, agent_mode=AgentMode.COPILOT_PLUGIN)
        assert result is None

    def test_returns_none_for_none_mode(self, tmp_path):
        result = build_copilot_cli_command(tmp_path, agent_mode=AgentMode.NONE)
        assert result is None

    def test_returns_string_for_cli_mode(self, tmp_path):
        result = build_copilot_cli_command(tmp_path, agent_mode=AgentMode.COPILOT_CLI)
        assert isinstance(result, str)

    def test_contains_copilot_binary(self, tmp_path):
        cmd = build_copilot_cli_command(tmp_path)
        assert "copilot" in cmd

    def test_contains_worktree_path(self, tmp_path):
        cmd = build_copilot_cli_command(tmp_path)
        assert str(tmp_path) in cmd

    def test_contains_cd_command(self, tmp_path):
        cmd = build_copilot_cli_command(tmp_path)
        assert "cd " in cmd

    def test_contains_instructions_dir_env(self, tmp_path):
        cmd = build_copilot_cli_command(tmp_path)
        assert "COPILOT_CUSTOM_INSTRUCTIONS_DIRS" in cmd
        assert ".github/instructions" in cmd

    def test_contains_deny_tool_flags(self, tmp_path):
        cmd = build_copilot_cli_command(tmp_path)
        assert "--deny-tool=" in cmd

    def test_git_push_denied(self, tmp_path):
        cmd = build_copilot_cli_command(tmp_path)
        assert "git push" in cmd

    def test_git_remote_add_denied(self, tmp_path):
        cmd = build_copilot_cli_command(tmp_path)
        assert "git remote add" in cmd

    def test_git_remote_set_url_denied(self, tmp_path):
        cmd = build_copilot_cli_command(tmp_path)
        assert "git remote set-url" in cmd

    def test_git_clone_denied(self, tmp_path):
        cmd = build_copilot_cli_command(tmp_path)
        assert "git clone" in cmd

    def test_all_deny_tools_in_command(self, tmp_path):
        cmd = build_copilot_cli_command(tmp_path)
        for tool in _DENY_TOOLS:
            # The tool name (without shell()) should appear in the cmd
            tool_cmd = tool.replace("shell(", "").rstrip(")")
            assert tool_cmd in cmd, f"Expected '{tool_cmd}' in deny-tool flags"

    def test_command_is_one_line(self, tmp_path):
        cmd = build_copilot_cli_command(tmp_path)
        # Should be a single line suitable for copy-paste
        assert "\n" not in cmd

    def test_real_copilot_syntax(self, tmp_path):
        """Verify the deny-tool syntax matches real Copilot CLI format."""
        cmd = build_copilot_cli_command(tmp_path)
        # Real syntax: --deny-tool='shell(git push)'
        assert "--deny-tool='shell(" in cmd or '--deny-tool="shell(' in cmd or "--deny-tool='shell(" in cmd


# ---------------------------------------------------------------------------
# DENY_TOOLS constant
# ---------------------------------------------------------------------------


class TestDenyToolsList:
    def test_has_required_tools(self):
        tool_cmds = [t.replace("shell(", "").rstrip(")") for t in _DENY_TOOLS]
        assert "git push" in tool_cmds
        assert "git remote add" in tool_cmds
        assert "git remote set-url" in tool_cmds
        assert "git clone" in tool_cmds

    def test_all_tools_are_shell_commands(self):
        for tool in _DENY_TOOLS:
            assert tool.startswith("shell("), f"Tool '{tool}' should start with 'shell('"
            assert tool.endswith(")"), f"Tool '{tool}' should end with ')'"


# ---------------------------------------------------------------------------
# COPILOT_CUSTOM_INSTRUCTIONS_DIRS in environment
# ---------------------------------------------------------------------------


class TestCopilotInstructionsEnv:
    def test_env_var_set_in_terminal_launch(self, tmp_path):
        from koteguard.launcher import IDELauncher
        import os

        launcher = IDELauncher(tmp_path)

        # Mock subprocess.Popen to capture env
        captured_env = {}

        def mock_popen(*args, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            return MagicMock()

        with patch("koteguard.launcher.subprocess.Popen", side_effect=mock_popen), \
             patch("koteguard.launcher.platform.system", return_value="Darwin"):
            launcher.open_terminal()

        assert "COPILOT_CUSTOM_INSTRUCTIONS_DIRS" in captured_env
        assert captured_env["COPILOT_CUSTOM_INSTRUCTIONS_DIRS"] == ".github/instructions"
