"""Comprehensive tests for koteguard/planning.py.

Covers render_plan, parse_plan (YAML + regex fallback), render_task, parse_task,
render_workspace, workspace_from_project_info, render_copilot_instructions,
render_security_instructions, and the markdown helper functions.
"""

from __future__ import annotations

import pytest

from koteguard.models import (
    AgentMode,
    PlanModel,
    PlanTask,
    ProjectInfo,
    ProjectType,
    TaskModel,
    WorkspaceModel,
)
from koteguard.planning import (
    _h2,
    _h2_text,
    _parse_plan_regex,
    parse_plan,
    parse_task,
    render_copilot_instructions,
    render_plan,
    render_security_instructions,
    render_task,
    render_workspace,
    workspace_from_project_info,
)

# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------


class TestMarkdownHelpers:
    def test_h2_basic(self):
        result = _h2("Section", ["item1", "item2"])
        assert "## Section" in result
        assert "- item1" in result
        assert "- item2" in result

    def test_h2_empty_items(self):
        result = _h2("Empty", [])
        assert "## Empty" in result
        assert "- " not in result

    def test_h2_text(self):
        result = _h2_text("Title", "Body text")
        assert "## Title" in result
        assert "Body text" in result


# ---------------------------------------------------------------------------
# render_plan
# ---------------------------------------------------------------------------


def _make_plan(**kwargs) -> PlanModel:
    defaults = {
        "title": "Test Plan",
        "objectives": ["Obj 1"],
        "tasks": ["Task 1"],
        "definition_of_done": ["Tests pass"],
        "estimated_time": "1 hour",
    }
    defaults.update(kwargs)
    return PlanModel(**defaults)


class TestRenderPlan:
    def test_starts_with_yaml_front_matter(self):
        md = render_plan(_make_plan())
        assert md.startswith("---\n")

    def test_contains_title(self):
        md = render_plan(_make_plan(title="My Feature"))
        assert "My Feature" in md

    def test_contains_task_checkboxes(self):
        md = render_plan(_make_plan(tasks=["Write code", "Write tests"]))
        assert "[ ]" in md
        assert "Write code" in md
        assert "Write tests" in md

    def test_done_task_checked(self):
        plan = PlanModel(
            title="Plan",
            objectives=["Obj"],
            tasks=[PlanTask(id="t1", description="Done task", done=True)],
            definition_of_done=["Done"],
        )
        md = render_plan(plan)
        assert "[x]" in md

    def test_contains_definition_of_done(self):
        md = render_plan(_make_plan(definition_of_done=["All green", "Reviewed"]))
        assert "All green" in md
        assert "Reviewed" in md

    def test_risks_section_included_when_present(self):
        md = render_plan(_make_plan(risks=["Breaking change", "Performance hit"]))
        assert "## Risks" in md
        assert "Breaking change" in md

    def test_risks_section_absent_when_empty(self):
        md = render_plan(_make_plan(risks=[]))
        assert "## Risks" not in md

    def test_android_skills_section_present(self):
        md = render_plan(_make_plan(android_skills=["navigation3", "agp9"]))
        assert "## Android Skills" in md
        assert "navigation3" in md

    def test_android_skills_absent_when_empty(self):
        md = render_plan(_make_plan(android_skills=[]))
        assert "## Android Skills" not in md

    def test_token_rules_section_always_present(self):
        md = render_plan(_make_plan())
        assert "Token & Context Rules" in md

    def test_estimated_time_in_output(self):
        md = render_plan(_make_plan(estimated_time="3 hours"))
        assert "3 hours" in md


# ---------------------------------------------------------------------------
# parse_plan – YAML front-matter path
# ---------------------------------------------------------------------------


class TestParsePlanYaml:
    def test_roundtrip(self):
        original = _make_plan(
            title="Roundtrip Plan",
            objectives=["Check round-trip"],
            tasks=["Task A", "Task B"],
            definition_of_done=["All done"],
        )
        md = render_plan(original)
        parsed = parse_plan(md)
        assert parsed.title == "Roundtrip Plan"
        assert len(parsed.tasks) == 2
        assert parsed.tasks[0].description == "Task A"

    def test_roundtrip_preserves_done_state(self):
        plan = PlanModel(
            title="Plan",
            objectives=["Obj"],
            tasks=[
                PlanTask(id="t1", description="Done", done=True),
                PlanTask(id="t2", description="Pending", done=False),
            ],
            definition_of_done=["Done"],
        )
        parsed = parse_plan(render_plan(plan))
        assert parsed.tasks[0].done is True
        assert parsed.tasks[1].done is False

    def test_roundtrip_android_skills(self):
        plan = _make_plan(android_skills=["navigation3", "compose-migration"])
        parsed = parse_plan(render_plan(plan))
        assert "navigation3" in parsed.android_skills

    def test_roundtrip_risks(self):
        plan = _make_plan(risks=["Risk 1"])
        parsed = parse_plan(render_plan(plan))
        assert "Risk 1" in parsed.risks

    def test_roundtrip_estimated_time(self):
        plan = _make_plan(estimated_time="2-3 hours")
        parsed = parse_plan(render_plan(plan))
        assert parsed.estimated_time == "2-3 hours"


# ---------------------------------------------------------------------------
# parse_plan – regex fallback path
# ---------------------------------------------------------------------------


class TestParsePlanRegex:
    def _legacy_plan(self) -> str:
        return """# My Legacy Plan

## Objectives

- Objective one
- Objective two

## Tasks

1. First task
2. Second task

## Definition of Done

- All tests pass
- Reviewed

## Estimated Time

2 hours

## Risks

- Database migration risk
"""

    def test_extracts_title(self):
        plan = _parse_plan_regex(self._legacy_plan())
        assert plan.title == "My Legacy Plan"

    def test_extracts_objectives(self):
        plan = _parse_plan_regex(self._legacy_plan())
        assert "Objective one" in plan.objectives

    def test_extracts_tasks(self):
        plan = _parse_plan_regex(self._legacy_plan())
        descs = [t.description for t in plan.tasks]
        assert "First task" in descs
        assert "Second task" in descs

    def test_extracts_definition_of_done(self):
        plan = _parse_plan_regex(self._legacy_plan())
        assert "All tests pass" in plan.definition_of_done

    def test_extracts_estimated_time(self):
        plan = _parse_plan_regex(self._legacy_plan())
        assert plan.estimated_time == "2 hours"

    def test_extracts_risks(self):
        plan = _parse_plan_regex(self._legacy_plan())
        assert "Database migration risk" in plan.risks

    def test_missing_title_defaults(self):
        plan = _parse_plan_regex("No heading here")
        assert plan.title == "Untitled Plan"

    def test_missing_sections_fallback_to_none(self):
        plan = _parse_plan_regex("# Title\n")
        assert plan.tasks[0].description == "(none)"

    def test_checkbox_tasks_extracted(self):
        md = "# Plan\n\n## Tasks\n\n1. [x] Done task\n2. [ ] Open task\n"
        plan = _parse_plan_regex(md)
        descs = [t.description for t in plan.tasks]
        assert "Done task" in descs
        assert "Open task" in descs

    def test_parse_plan_falls_back_to_regex_for_bad_yaml(self):
        """parse_plan should fall back to regex when YAML front-matter is malformed."""
        md = "---\nnot valid: yaml: [\nbad\n---\n\n# Plan\n## Tasks\n1. Task A\n"
        plan = parse_plan(md)
        assert plan is not None  # fallback returned something

    def test_parse_plan_no_frontmatter_uses_regex(self):
        md = "# Simple Plan\n\n## Tasks\n\n1. Only task\n\n## Definition of Done\n\n- Done\n"
        plan = parse_plan(md)
        assert plan.title == "Simple Plan"
        assert any(t.description == "Only task" for t in plan.tasks)


# ---------------------------------------------------------------------------
# render_task / parse_task
# ---------------------------------------------------------------------------


class TestRenderTask:
    def test_starts_with_front_matter(self):
        task = TaskModel(session_id="abc-123", description="Fix bug")
        md = render_task(task)
        assert md.startswith("---\n")

    def test_contains_session_id(self):
        task = TaskModel(session_id="sess-01", description="Feature")
        md = render_task(task)
        assert "sess-01" in md

    def test_contains_description(self):
        task = TaskModel(session_id="abc-123", description="Do the thing")
        md = render_task(task)
        assert "Do the thing" in md

    def test_constraints_rendered(self):
        task = TaskModel(
            session_id="abc-123",
            description="Task",
            constraints=["No git push", "Stay on branch"],
        )
        md = render_task(task)
        assert "No git push" in md
        assert "Stay on branch" in md

    def test_empty_constraints_shows_none(self):
        task = TaskModel(session_id="abc-123", description="Task")
        md = render_task(task)
        assert "(none)" in md

    def test_context_rendered(self):
        task = TaskModel(session_id="abc-123", description="Task", context="Some context info")
        md = render_task(task)
        assert "Some context info" in md


class TestParseTask:
    def test_roundtrip(self):
        original = TaskModel(
            session_id="abc-123",
            description="Fix login flow",
            context="Context",
            constraints=["No push"],
        )
        md = render_task(original)
        parsed = parse_task(md)
        assert parsed.session_id == "abc-123"
        assert parsed.description == "Fix login flow"

    def test_regex_fallback(self):
        md = "# Task: Some task\n\n`my-sess-id` is the session.\n"
        parsed = parse_task(md)
        assert parsed.session_id == "my-sess-id"

    def test_fallback_unknown_session(self):
        md = "# Task: Something\n\nNo backticks here.\n"
        parsed = parse_task(md)
        assert parsed.session_id == "unknown-session"


# ---------------------------------------------------------------------------
# render_workspace
# ---------------------------------------------------------------------------


class TestRenderWorkspace:
    def test_contains_project_name(self):
        ws = WorkspaceModel(project_name="SuperApp", tech_stack=["Kotlin"])
        md = render_workspace(ws)
        assert "SuperApp" in md

    def test_tech_stack_listed(self):
        ws = WorkspaceModel(project_name="App", tech_stack=["Kotlin", "Compose"])
        md = render_workspace(ws)
        assert "Kotlin" in md
        assert "Compose" in md

    def test_architecture_section_present_when_set(self):
        ws = WorkspaceModel(project_name="App", tech_stack=["Swift"], architecture="VIPER")
        md = render_workspace(ws)
        assert "## Architecture" in md
        assert "VIPER" in md

    def test_architecture_absent_when_empty(self):
        ws = WorkspaceModel(project_name="App", tech_stack=["Kotlin"])
        md = render_workspace(ws)
        assert "## Architecture" not in md

    def test_conventions_section(self):
        ws = WorkspaceModel(
            project_name="App",
            tech_stack=["Kotlin"],
            conventions=["Use coroutines", "MVVM only"],
        )
        md = render_workspace(ws)
        assert "## Conventions" in md
        assert "Use coroutines" in md

    def test_structure_section(self):
        ws = WorkspaceModel(
            project_name="App",
            tech_stack=["Kotlin"],
            structure={"app/src/": "Main source"},
        )
        md = render_workspace(ws)
        assert "## Project Structure" in md
        assert "app/src/" in md

    def test_gotchas_section(self):
        ws = WorkspaceModel(
            project_name="App",
            tech_stack=["Kotlin"],
            gotchas=["Don't commit secrets"],
        )
        md = render_workspace(ws)
        assert "Gotchas" in md
        assert "Don't commit secrets" in md

    def test_android_agent_stack_section(self):
        ws = WorkspaceModel(
            project_name="App",
            tech_stack=["Kotlin"],
            android_agent_stack={
                "cli_version": "available",
                "kb_status": "ready",
                "enabled_skills": ["navigation3"],
            },
        )
        md = render_workspace(ws)
        assert "## Android Agent Stack" in md
        assert "navigation3" in md

    def test_android_agent_stack_absent_when_empty(self):
        ws = WorkspaceModel(project_name="App", tech_stack=["Kotlin"])
        md = render_workspace(ws)
        assert "## Android Agent Stack" not in md

    def test_workspace_header_format(self):
        ws = WorkspaceModel(project_name="TestApp", tech_stack=["Kotlin"])
        md = render_workspace(ws)
        assert md.startswith("# WORKSPACE: TestApp")


# ---------------------------------------------------------------------------
# workspace_from_project_info
# ---------------------------------------------------------------------------


class TestWorkspaceFromProjectInfo:
    def test_android_project(self):
        info = ProjectInfo(
            project_type=ProjectType.ANDROID,
            project_name="MyApp",
            frameworks=["Android SDK", "Gradle"],
            languages=["Kotlin"],
            android_package="com.example.myapp",
            android_min_sdk=26,
            has_ci=True,
        )
        ws = workspace_from_project_info(info)
        assert ws.project_name == "MyApp"
        assert any("Android" in t for t in ws.tech_stack)
        assert "CI is configured" in " ".join(ws.conventions)
        assert any("keystore" in g.lower() for g in ws.gotchas)

    def test_ios_project(self):
        info = ProjectInfo(
            project_type=ProjectType.IOS,
            project_name="iOSApp",
            frameworks=["UIKit/SwiftUI"],
            languages=["Swift"],
            ios_bundle_id="com.example.ios",
        )
        ws = workspace_from_project_info(info)
        assert ws.project_name == "iOSApp"
        assert "UIKit/SwiftUI" in ws.tech_stack
        assert any("certificate" in g.lower() or "p12" in g.lower() for g in ws.gotchas)

    def test_unknown_project_type(self):
        info = ProjectInfo(project_type=ProjectType.UNKNOWN, project_name="Unknown")
        ws = workspace_from_project_info(info)
        assert "unknown" in ws.tech_stack

    def test_empty_frameworks_falls_back_to_project_type(self):
        info = ProjectInfo(project_type=ProjectType.ANDROID, project_name="App")
        ws = workspace_from_project_info(info)
        assert len(ws.tech_stack) > 0

    def test_android_with_doc_summary_patterns(self):
        info = ProjectInfo(
            project_type=ProjectType.ANDROID,
            project_name="App",
            frameworks=["Android SDK"],
            doc_summary={"README.md": ["[keyword:mvvm]", "[keyword:repository]"]},
        )
        ws = workspace_from_project_info(info)
        assert "mvvm" in ws.architecture.lower()

    def test_android_cli_available_in_stack(self):
        info = ProjectInfo(
            project_type=ProjectType.ANDROID,
            project_name="App",
            frameworks=["Android SDK"],
            android_cli_available=True,
        )
        ws = workspace_from_project_info(info)
        assert ws.android_agent_stack.get("cli_version") == "available"

    def test_android_cli_not_available_in_stack(self):
        info = ProjectInfo(
            project_type=ProjectType.ANDROID,
            project_name="App",
            frameworks=["Android SDK"],
            android_cli_available=False,
        )
        ws = workspace_from_project_info(info)
        assert ws.android_agent_stack.get("cli_version") == "not detected"

    def test_ios_bundle_id_in_structure(self):
        info = ProjectInfo(
            project_type=ProjectType.IOS,
            project_name="App",
            ios_bundle_id="com.example",
        )
        ws = workspace_from_project_info(info)
        assert "com.example" in str(ws.structure)


# ---------------------------------------------------------------------------
# render_copilot_instructions
# ---------------------------------------------------------------------------


class TestRenderCopilotInstructions:
    def _ws(self, **kwargs):
        defaults = {"project_name": "TestApp", "tech_stack": ["Kotlin"]}
        defaults.update(kwargs)
        return WorkspaceModel(**defaults)

    def _plan(self):
        return PlanModel(
            title="Fix login",
            objectives=["Improve login flow"],
            tasks=["Refactor auth", "Add tests"],
            definition_of_done=["Tests pass"],
        )

    def test_contains_session_id(self):
        instructions = render_copilot_instructions(self._plan(), self._ws(), "sess-abc")
        assert "sess-abc" in instructions

    def test_contains_project_name(self):
        instructions = render_copilot_instructions(self._plan(), self._ws(), "sess-abc")
        assert "TestApp" in instructions

    def test_contains_plan_title(self):
        instructions = render_copilot_instructions(self._plan(), self._ws(), "sess-abc")
        assert "Fix login" in instructions

    def test_contains_tasks(self):
        instructions = render_copilot_instructions(self._plan(), self._ws(), "sess-abc")
        assert "Refactor auth" in instructions
        assert "Add tests" in instructions

    def test_contains_definition_of_done(self):
        instructions = render_copilot_instructions(self._plan(), self._ws(), "sess-abc")
        assert "Tests pass" in instructions

    def test_contains_constraints(self):
        instructions = render_copilot_instructions(self._plan(), self._ws(), "sess-abc")
        assert "No git push" in instructions or "git push" in instructions

    def test_android_section_when_stack_and_cli_enabled(self):
        ws = self._ws(
            android_agent_stack={
                "cli_version": "available",
                "kb_status": "ready",
                "enabled_skills": ["navigation3"],
            }
        )
        instructions = render_copilot_instructions(
            self._plan(), ws, "sess-abc", android_cli_enabled=True
        )
        assert "Android Agent Stack" in instructions
        assert "navigation3" in instructions

    def test_android_section_absent_when_cli_disabled(self):
        ws = self._ws(
            android_agent_stack={
                "cli_version": "available",
                "kb_status": "ready",
                "enabled_skills": ["navigation3"],
            }
        )
        instructions = render_copilot_instructions(
            self._plan(), ws, "sess-abc", android_cli_enabled=False
        )
        assert "Android Agent Stack" not in instructions

    def test_done_tasks_marked_with_check(self):
        plan = PlanModel(
            title="Plan",
            objectives=["Obj"],
            tasks=[
                PlanTask(id="t1", description="Done task", done=True),
                PlanTask(id="t2", description="Open task", done=False),
            ],
            definition_of_done=["Done"],
        )
        instructions = render_copilot_instructions(plan, self._ws(), "sess-abc")
        assert "✓" in instructions

    def test_worktree_isolation_notice(self):
        instructions = render_copilot_instructions(self._plan(), self._ws(), "sess-abc")
        assert (
            "isolated git worktree" in instructions.lower() or "NOT in the primary" in instructions
        )


# ---------------------------------------------------------------------------
# render_security_instructions
# ---------------------------------------------------------------------------


class TestRenderSecurityInstructions:
    def test_contains_deny_by_default_rules(self):
        result = render_security_instructions()
        assert "Deny-by-Default" in result or "No secrets" in result

    def test_android_section_for_android_type(self):
        result = render_security_instructions(project_type="android", android_cli_enabled=True)
        assert "*.jks" in result
        assert "google-services.json" in result

    def test_android_cli_block_when_enabled(self):
        result = render_security_instructions(project_type="android", android_cli_enabled=True)
        assert "Android CLI Commands" in result

    def test_android_cli_block_absent_when_disabled(self):
        result = render_security_instructions(project_type="android", android_cli_enabled=False)
        assert "Android CLI Commands" not in result

    def test_ios_section_for_ios_type(self):
        result = render_security_instructions(project_type="ios")
        assert "*.p12" in result
        assert "*.mobileprovision" in result

    def test_monorepo_has_both_sections(self):
        result = render_security_instructions(project_type="monorepo", android_cli_enabled=True)
        assert "*.jks" in result
        assert "*.p12" in result

    def test_unknown_type_has_both_sections(self):
        result = render_security_instructions(project_type="unknown")
        assert "*.jks" in result
        assert "*.p12" in result

    def test_allowed_git_commands_listed(self):
        result = render_security_instructions()
        assert "git status" in result
        assert "git commit" in result

    def test_forbidden_git_push(self):
        result = render_security_instructions()
        assert "git push" in result
        assert "Forbidden" in result or "forbidden" in result

    def test_has_applyto_header(self):
        result = render_security_instructions()
        assert 'applyTo: "**/*"' in result
