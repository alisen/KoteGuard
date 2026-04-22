"""Tests for Spec-Driven Development features: YAML front-matter, task tracking, semantic validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from koteguard.models import PlanModel, PlanTask, TaskModel
from koteguard.planning import (
    parse_plan,
    parse_task,
    render_plan,
    render_task,
)
from koteguard.validation import (
    ValidationResult,
    _file_matches_task,
    _task_keywords,
    validate_changes_against_plan,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _make_plan(**kwargs) -> PlanModel:
    defaults = dict(
        title="Implement NavGraph",
        objectives=["Add navigation stack"],
        tasks=[PlanTask(id="t1", description="Create NavGraph"), PlanTask(id="t2", description="Add deep links")],
        definition_of_done=["All tests pass"],
        estimated_time="1 hour",
    )
    defaults.update(kwargs)
    return PlanModel(**defaults)


# ---------------------------------------------------------------------------
# YAML front-matter round-trip
# ---------------------------------------------------------------------------


class TestYAMLRoundTrip:
    def test_render_produces_front_matter(self):
        plan = _make_plan()
        rendered = render_plan(plan)
        assert rendered.startswith("---")
        assert "title:" in rendered
        assert "tasks:" in rendered

    def test_parse_reads_yaml_front_matter(self):
        plan = _make_plan()
        rendered = render_plan(plan)
        parsed = parse_plan(rendered)
        assert parsed.title == plan.title
        assert len(parsed.tasks) == len(plan.tasks)
        assert parsed.tasks[0].id == "t1"
        assert parsed.tasks[0].description == "Create NavGraph"

    def test_round_trip_preserves_task_done_status(self):
        tasks = [
            PlanTask(id="t1", description="Create NavGraph", done=True),
            PlanTask(id="t2", description="Add deep links", done=False),
        ]
        plan = _make_plan(tasks=tasks)
        rendered = render_plan(plan)
        parsed = parse_plan(rendered)
        assert parsed.tasks[0].done is True
        assert parsed.tasks[1].done is False

    def test_round_trip_preserves_android_skills(self):
        plan = _make_plan(android_skills=["navigation3", "compose-migration"])
        parsed = parse_plan(render_plan(plan))
        assert "navigation3" in parsed.android_skills
        assert "compose-migration" in parsed.android_skills

    def test_round_trip_preserves_spec_version(self):
        plan = _make_plan()
        parsed = parse_plan(render_plan(plan))
        assert parsed.spec_version == "1.0"

    def test_multiple_round_trips_stable(self):
        """Parsing a rendered plan and re-rendering should be idempotent."""
        plan = _make_plan()
        rendered1 = render_plan(plan)
        parsed1 = parse_plan(rendered1)
        rendered2 = render_plan(parsed1)
        parsed2 = parse_plan(rendered2)
        assert parsed1.title == parsed2.title
        assert len(parsed1.tasks) == len(parsed2.tasks)


# ---------------------------------------------------------------------------
# Corrupted YAML — fallback to regex
# ---------------------------------------------------------------------------


class TestCorruptedYAMLFallback:
    def test_corrupted_yaml_falls_back_to_regex(self):
        """If agent corrupts the YAML block, parse_plan falls back to regex — no crash."""
        corrupted_md = """\
---
title: My Plan
tasks: [this is invalid: yaml: {
---

# My Plan

## Objectives

- Do something

## Tasks

1. Task one

## Definition of Done

- Done
"""
        result = parse_plan(corrupted_md)
        # Should not crash; fallback gives us at least a title
        assert result.title == "My Plan"
        assert len(result.tasks) >= 1

    def test_no_yaml_block_falls_back_to_regex(self):
        """Legacy markdown without front-matter still parses correctly."""
        legacy_md = """\
# Legacy Plan

## Objectives

- Implement feature

## Tasks

1. Write code
2. Write tests

## Definition of Done

- All tests pass
"""
        result = parse_plan(legacy_md)
        assert result.title == "Legacy Plan"
        assert len(result.tasks) == 2
        assert result.tasks[0].description == "Write code"

    def test_empty_yaml_block_falls_back_to_regex(self):
        md = """\
---
---

# My Plan

## Objectives

- o

## Tasks

1. A task

## Definition of Done

- done
"""
        result = parse_plan(md)
        assert result.title == "My Plan"


# ---------------------------------------------------------------------------
# Task done-flag tracking
# ---------------------------------------------------------------------------


class TestTaskDoneTracking:
    def test_all_undone_warning_when_files_changed(self, tmp_path):
        """If agent changed files but marked no tasks done, a warning is issued."""
        plan = _make_plan()  # all tasks done=False by default
        plan_file = _write(tmp_path / "PLAN.md", render_plan(plan))
        result = validate_changes_against_plan(
            tmp_path,
            plan_file,
            changed_files=["app/src/main/java/NavGraph.kt"],
        )
        assert any("done: true" in w or "done:true" in w or "marked" in w.lower()
                   for w in result.warnings)

    def test_done_tasks_dont_trigger_warning(self, tmp_path):
        """If all tasks are marked done, no done-flag warning."""
        tasks = [
            PlanTask(id="t1", description="Create NavGraph", done=True),
            PlanTask(id="t2", description="Add deep links", done=True),
        ]
        plan = _make_plan(tasks=tasks)
        plan_file = _write(tmp_path / "PLAN.md", render_plan(plan))
        result = validate_changes_against_plan(
            tmp_path,
            plan_file,
            changed_files=["app/src/main/java/NavGraph.kt"],
        )
        # No done-flag warning when tasks are marked complete
        done_warnings = [w for w in result.warnings if "done" in w.lower() and "marked" in w.lower()]
        assert len(done_warnings) == 0


# ---------------------------------------------------------------------------
# CamelCase keyword matching
# ---------------------------------------------------------------------------


class TestTaskKeywords:
    def test_camelcase_splitting(self):
        """NavGraph → {'nav', 'graph'}"""
        kws = _task_keywords("Create NavGraph")
        assert "nav" in kws
        assert "graph" in kws

    def test_lowercase_words(self):
        kws = _task_keywords("add deep links")
        assert "add" in kws
        assert "deep" in kws
        assert "links" in kws

    def test_short_words_excluded(self):
        kws = _task_keywords("do it now")
        # 'do', 'it' are 2 chars → excluded; 'now' is 3 chars
        assert "do" not in kws
        assert "it" not in kws
        assert "now" in kws

    def test_file_matches_via_camelcase(self):
        kws = _task_keywords("Create NavGraph")
        assert _file_matches_task("app/src/main/java/navigation/NavGraph.kt", kws)

    def test_file_no_match(self):
        kws = _task_keywords("Create NavGraph")
        assert not _file_matches_task("app/src/main/res/layout/activity_main.xml", kws)

    def test_case_insensitive_match(self):
        kws = _task_keywords("create NavGraph")
        assert _file_matches_task("app/navigation/navgraph.kt", kws)


# ---------------------------------------------------------------------------
# Semantic task-to-file matching
# ---------------------------------------------------------------------------


class TestSemanticValidation:
    def test_matching_file_suppresses_warning(self, tmp_path):
        plan = _make_plan()  # t1: "Create NavGraph", t2: "Add deep links"
        plan_file = _write(tmp_path / "PLAN.md", render_plan(plan))
        # Provide files that match both tasks
        changed = [
            "app/src/main/java/navigation/NavGraph.kt",
            "app/src/main/java/links/DeepLink.kt",
        ]
        result = validate_changes_against_plan(tmp_path, plan_file, changed)
        task_missing_warnings = [
            w for w in result.warnings if "no matching changed files" in w
        ]
        assert len(task_missing_warnings) == 0

    def test_unrelated_files_warn_per_task(self, tmp_path):
        """Files unrelated to task descriptions should produce per-task warnings."""
        plan = _make_plan()
        plan_file = _write(tmp_path / "PLAN.md", render_plan(plan))
        changed = ["app/src/main/res/values/strings.xml"]  # unrelated
        result = validate_changes_against_plan(tmp_path, plan_file, changed)
        # At least one task should have a "no matching" warning
        task_missing_warnings = [
            w for w in result.warnings if "no matching changed files" in w
        ]
        assert len(task_missing_warnings) > 0


# ---------------------------------------------------------------------------
# TASK.md YAML front-matter
# ---------------------------------------------------------------------------


class TestTaskModelYAML:
    def test_render_task_has_front_matter(self):
        task = TaskModel(session_id="abc-123", description="Build login screen")
        rendered = render_task(task)
        assert rendered.startswith("---")
        assert "session_id:" in rendered
        assert "description:" in rendered

    def test_parse_task_round_trip(self):
        task = TaskModel(
            session_id="abc-123",
            description="Build login screen",
            context="Use Material 3",
            constraints=["No third-party auth libs"],
        )
        rendered = render_task(task)
        parsed = parse_task(rendered)
        assert parsed.session_id == "abc-123"
        assert parsed.description == "Build login screen"
        assert parsed.context == "Use Material 3"
        assert "No third-party auth libs" in parsed.constraints

    def test_parse_task_corrupted_yaml_fallback(self):
        corrupted = """\
---
invalid yaml: {{{
---

# Task: My task

**Session:** `abc-123`
"""
        result = parse_task(corrupted)
        # Fallback should still extract session_id and description
        assert result.session_id == "abc-123"
        assert "My task" in result.description
