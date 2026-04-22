"""Tests for Copilot CLI deny flags and COPILOT_CUSTOM_INSTRUCTIONS_DIRS."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from koteguard.cli import _build_starter_message
from koteguard.launcher import _DENY_TOOLS, build_copilot_cli_command
from koteguard.models import AgentMode, PlanModel, PlanTask, ProjectInfo, ProjectType

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
        import os

        from koteguard.launcher import IDELauncher

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


# ---------------------------------------------------------------------------
# _build_starter_message
# ---------------------------------------------------------------------------


def _android_info(**kwargs) -> ProjectInfo:
    defaults = dict(
        project_type=ProjectType.ANDROID,
        project_name="my-app",
        android_min_sdk=21,
        android_target_sdk=35,
        android_compile_sdk=35,
    )
    defaults.update(kwargs)
    return ProjectInfo(**defaults)


def _ios_info(**kwargs) -> ProjectInfo:
    defaults = dict(
        project_type=ProjectType.IOS,
        project_name="my-ios-app",
        ios_deployment_target="16.0",
    )
    defaults.update(kwargs)
    return ProjectInfo(**defaults)


def _plan(tasks=None, skills=None, dod=None) -> PlanModel:
    return PlanModel(
        title="Test Plan",
        objectives=["Objective 1"],
        tasks=tasks or [PlanTask(id="t1", description="Do the thing", done=False)],
        definition_of_done=dod or ["All tests pass"],
        android_skills=skills or [],
    )


class TestBuildStarterMessage:
    def test_starts_with_read_instruction(self):
        msg = _build_starter_message(_android_info(), _plan())
        assert msg.startswith("Read PLAN.md and TASK.md.")

    def test_android_sdk_versions_included(self):
        msg = _build_starter_message(_android_info(), _plan())
        assert "minSdk=21" in msg
        assert "targetSdk=35" in msg
        assert "compileSdk=35" in msg

    def test_android_missing_sdk_omitted(self):
        info = _android_info(android_min_sdk=None, android_target_sdk=None, android_compile_sdk=None)
        msg = _build_starter_message(info, _plan())
        assert "minSdk" not in msg
        assert "targetSdk" not in msg

    def test_ios_deployment_target_included(self):
        msg = _build_starter_message(_ios_info(), _plan())
        assert "minOS=16.0" in msg
        assert "android" not in msg.lower()

    def test_ios_no_deployment_target_omitted(self):
        info = _ios_info(ios_deployment_target=None)
        msg = _build_starter_message(info, _plan())
        assert "minOS" not in msg

    def test_task_ids_included(self):
        tasks = [
            PlanTask(id="t1", description="First task", done=False),
            PlanTask(id="t2", description="Second task", done=False),
        ]
        msg = _build_starter_message(_android_info(), _plan(tasks=tasks))
        assert "Task [t1]: First task" in msg
        assert "Task [t2]: Second task" in msg

    def test_skills_included_when_present(self):
        msg = _build_starter_message(_android_info(), _plan(skills=["navigation3", "compose-migration"]))
        assert "navigation3" in msg
        assert "compose-migration" in msg
        assert "Refer to them" in msg

    def test_skills_omitted_when_empty(self):
        msg = _build_starter_message(_android_info(), _plan(skills=[]))
        assert "Skill guides" not in msg

    def test_sdd_instruction_always_present(self):
        msg = _build_starter_message(_android_info(), _plan())
        assert "done: true" in msg
        assert "PLAN.md YAML" in msg

    def test_definition_of_done_included(self):
        msg = _build_starter_message(_android_info(), _plan(dod=["All warnings resolved", "Tests pass"]))
        assert "All warnings resolved" in msg
        assert "Tests pass" in msg

    def test_project_name_in_output(self):
        info = _android_info(project_name="cool-project")
        msg = _build_starter_message(info, _plan())
        assert "cool-project" in msg

    def test_plain_text_no_rich_markup(self):
        msg = _build_starter_message(_android_info(), _plan())
        assert "[bold]" not in msg
        assert "[green]" not in msg
        assert "[/]" not in msg
