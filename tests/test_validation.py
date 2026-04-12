"""Tests for validation utilities."""

from __future__ import annotations

from pathlib import Path

import pytest

from koteguard.validation import (
    ValidationResult,
    validate_changes_against_plan,
    validate_plan_file,
    validate_workspace_file,
)
from koteguard.planning import render_plan, render_workspace
from koteguard.models import PlanModel, WorkspaceModel


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _valid_plan_md() -> str:
    plan = PlanModel(
        title="Add dark mode",
        objectives=["Support system dark mode"],
        tasks=["Update theme", "Test on device"],
        definition_of_done=["Tests pass", "Reviewed"],
        estimated_time="1 hour",
    )
    return render_plan(plan)


def _valid_workspace_md() -> str:
    ws = WorkspaceModel(
        project_name="MyApp",
        tech_stack=["Kotlin", "Android SDK"],
        architecture="MVVM",
    )
    return render_workspace(ws)


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------


class TestValidationResult:
    def test_starts_valid(self):
        r = ValidationResult()
        assert r.is_valid is True
        assert bool(r) is True

    def test_add_error_marks_invalid(self):
        r = ValidationResult()
        r.add_error("something wrong")
        assert r.is_valid is False
        assert bool(r) is False
        assert "something wrong" in r.errors

    def test_add_warning_keeps_valid(self):
        r = ValidationResult()
        r.add_warning("hmm")
        assert r.is_valid is True
        assert "hmm" in r.warnings


# ---------------------------------------------------------------------------
# validate_plan_file
# ---------------------------------------------------------------------------


class TestValidatePlanFile:
    def test_valid_plan(self, tmp_path):
        plan_file = _write(tmp_path / "PLAN.md", _valid_plan_md())
        result = validate_plan_file(plan_file)
        assert result.is_valid

    def test_missing_file(self, tmp_path):
        result = validate_plan_file(tmp_path / "PLAN.md")
        assert not result.is_valid
        assert any("not found" in e for e in result.errors)

    def test_empty_file(self, tmp_path):
        plan_file = _write(tmp_path / "PLAN.md", "")
        result = validate_plan_file(plan_file)
        assert not result.is_valid

    def test_placeholder_task_warns(self, tmp_path):
        md = """# My Plan

## Objectives

- Do something

## Tasks

1. (none)

## Definition of Done

- Done
"""
        plan_file = _write(tmp_path / "PLAN.md", md)
        result = validate_plan_file(plan_file)
        # Placeholder warning expected
        assert any("placeholder" in w.lower() for w in result.warnings)

    def test_unknown_estimated_time_warns(self, tmp_path):
        plan = PlanModel(
            title="Test",
            objectives=["o"],
            tasks=["t"],
            definition_of_done=["d"],
            estimated_time="unknown",
        )
        plan_file = _write(tmp_path / "PLAN.md", render_plan(plan))
        result = validate_plan_file(plan_file)
        assert any("estimated time" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# validate_workspace_file
# ---------------------------------------------------------------------------


class TestValidateWorkspaceFile:
    def test_valid_workspace(self, tmp_path):
        ws_file = _write(tmp_path / "WORKSPACE.md", _valid_workspace_md())
        result = validate_workspace_file(ws_file)
        assert result.is_valid

    def test_missing_file(self, tmp_path):
        result = validate_workspace_file(tmp_path / "WORKSPACE.md")
        assert not result.is_valid

    def test_empty_file(self, tmp_path):
        ws_file = _write(tmp_path / "WORKSPACE.md", "")
        result = validate_workspace_file(ws_file)
        assert not result.is_valid

    def test_missing_header_fails(self, tmp_path):
        ws_file = _write(tmp_path / "WORKSPACE.md", "# Not a workspace file\n")
        result = validate_workspace_file(ws_file)
        assert not result.is_valid

    def test_no_tech_stack_warns(self, tmp_path):
        ws_file = _write(tmp_path / "WORKSPACE.md", "# WORKSPACE: App\n\n## Architecture\n\nMVVM\n")
        result = validate_workspace_file(ws_file)
        assert any("tech stack" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# validate_changes_against_plan
# ---------------------------------------------------------------------------


class TestValidateChangesAgainstPlan:
    def test_no_changed_files_warns(self, tmp_path):
        plan_file = _write(tmp_path / "PLAN.md", _valid_plan_md())
        result = validate_changes_against_plan(tmp_path, plan_file, [])
        assert any("no changed" in w.lower() for w in result.warnings)

    def test_ci_workflow_change_warns(self, tmp_path):
        plan_file = _write(tmp_path / "PLAN.md", _valid_plan_md())
        changed = [".github/workflows/ci.yml"]
        result = validate_changes_against_plan(tmp_path, plan_file, changed)
        assert any("CI" in w for w in result.warnings)

    def test_normal_changes_no_warning(self, tmp_path):
        plan_file = _write(tmp_path / "PLAN.md", _valid_plan_md())
        changed = ["src/main/Theme.kt", "src/test/ThemeTest.kt"]
        result = validate_changes_against_plan(tmp_path, plan_file, changed)
        # CI warning should NOT appear
        assert not any("CI" in w for w in result.warnings)

    def test_invalid_plan_fails_early(self, tmp_path):
        plan_file = _write(tmp_path / "PLAN.md", "")
        result = validate_changes_against_plan(tmp_path, plan_file, ["file.kt"])
        assert not result.is_valid
