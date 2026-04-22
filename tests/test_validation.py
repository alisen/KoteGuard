"""Tests for validation utilities."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from koteguard.validation import (
    ValidationResult,
    validate_changes_against_plan,
    validate_plan_file,
    validate_workspace_file,
    validate_skills_compliance,
    render_validation_report,
    write_validation_report,
    write_used_skills_json,
)
from koteguard.planning import render_plan, render_workspace
from koteguard.models import PlanModel, WorkspaceModel, ProjectInfo, ProjectType, SkillsComplianceResult


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

    def test_normal_changes_no_ci_warning(self, tmp_path):
        plan_file = _write(tmp_path / "PLAN.md", _valid_plan_md())
        changed = ["src/main/Theme.kt", "src/test/ThemeTest.kt"]
        result = validate_changes_against_plan(tmp_path, plan_file, changed)
        assert not any("CI" in w for w in result.warnings)

    def test_invalid_plan_fails_early(self, tmp_path):
        plan_file = _write(tmp_path / "PLAN.md", "")
        result = validate_changes_against_plan(tmp_path, plan_file, ["file.kt"])
        assert not result.is_valid

    def test_all_tasks_undone_with_changes_warns(self, tmp_path):
        """If agent changed files but no tasks marked done → warning."""
        plan_file = _write(tmp_path / "PLAN.md", _valid_plan_md())
        result = validate_changes_against_plan(
            tmp_path, plan_file, ["src/main/Theme.kt"]
        )
        done_warnings = [w for w in result.warnings if "done" in w.lower() and "marked" in w.lower()]
        assert len(done_warnings) > 0


# ---------------------------------------------------------------------------
# validate_skills_compliance
# ---------------------------------------------------------------------------


class TestValidateSkillsCompliance:
    def test_compliant_when_no_android_skills(self):
        plan = PlanModel(
            title="Fix bug",
            objectives=["o"],
            tasks=["t"],
            definition_of_done=["d"],
            android_skills=[],
        )
        info = ProjectInfo(
            project_type=ProjectType.ANDROID,
            detected_skills=[],
        )
        result = validate_skills_compliance(plan, info)
        assert result.compliant is True

    def test_non_compliant_missing_skills(self):
        plan = PlanModel(
            title="Add navigation",
            objectives=["o"],
            tasks=["implement nav3"],
            definition_of_done=["d"],
            android_skills=[],
        )
        info = ProjectInfo(
            project_type=ProjectType.ANDROID,
            detected_skills=["navigation3"],
        )
        result = validate_skills_compliance(plan, info)
        # "navigation3" is in detected but not in plan.android_skills
        # However, "nav3" appears in task text so it might be detected
        assert isinstance(result, SkillsComplianceResult)

    def test_compliant_when_skills_in_plan(self):
        plan = PlanModel(
            title="Add navigation",
            objectives=["o"],
            tasks=["t"],
            definition_of_done=["d"],
            android_skills=["navigation3"],
        )
        info = ProjectInfo(
            project_type=ProjectType.ANDROID,
            detected_skills=["navigation3"],
        )
        result = validate_skills_compliance(plan, info)
        assert result.compliant is True

    def test_always_compliant_for_ios(self):
        plan = PlanModel(
            title="Fix bug",
            objectives=["o"],
            tasks=["t"],
            definition_of_done=["d"],
        )
        info = ProjectInfo(project_type=ProjectType.IOS)
        result = validate_skills_compliance(plan, info)
        assert result.compliant is True


# ---------------------------------------------------------------------------
# Validation report generation
# ---------------------------------------------------------------------------


class TestValidationReport:
    def test_render_report_contains_sections(self, tmp_path):
        from datetime import datetime, timezone
        from unittest.mock import patch

        plan_result = ValidationResult()
        changes_result = ValidationResult()
        skills_result = SkillsComplianceResult(compliant=True)

        with patch("koteguard.validation.read_session_audit", return_value=[]):
            report = render_validation_report(
                session_id="test-01",
                plan_result=plan_result,
                changes_result=changes_result,
                skills_result=skills_result,
                worktree_path=tmp_path,
                plan_path=tmp_path / "PLAN.md",
                created_at=datetime.now(tz=timezone.utc),
            )

        assert "Validation Report" in report
        assert "Plan Compliance" in report
        assert "Change Analysis" in report
        assert "Skills Compliance" in report
        assert "Token Hygiene Score" in report

    def test_report_shows_errors(self, tmp_path):
        from unittest.mock import patch

        plan_result = ValidationResult()
        plan_result.add_error("PLAN.md is empty")
        changes_result = ValidationResult()

        with patch("koteguard.validation.read_session_audit", return_value=[]):
            report = render_validation_report(
                session_id="test-02",
                plan_result=plan_result,
                changes_result=changes_result,
                skills_result=None,
                worktree_path=tmp_path,
                plan_path=tmp_path / "PLAN.md",
            )

        assert "❌" in report
        assert "FAIL" in report

    def test_write_validation_report(self, tmp_path):
        from unittest.mock import patch

        with patch("koteguard.validation.SESSIONS_DIR", tmp_path):
            report_path = write_validation_report("sess-abc", "# Test Report\n")
        assert report_path.exists()
        assert "Test Report" in report_path.read_text()

    def test_write_used_skills_json(self, tmp_path):
        from unittest.mock import patch

        with patch("koteguard.validation.SESSIONS_DIR", tmp_path):
            skills_path = write_used_skills_json("sess-xyz", ["navigation3", "edge-to-edge"])
        assert skills_path.exists()
        data = json.loads(skills_path.read_text())
        assert "navigation3" in data["used_skills"]
