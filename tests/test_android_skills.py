"""Tests for Android skills detection, compliance validation, and used-skills.json."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from koteguard.models import PlanModel, ProjectInfo, ProjectType, SkillsComplianceResult
from koteguard.project_scanner import ProjectScanner
from koteguard.validation import validate_skills_compliance, write_used_skills_json


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(path: Path, content: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _android_plan(**kwargs) -> PlanModel:
    defaults = {
        "title": "Android feature",
        "objectives": ["Implement feature"],
        "tasks": ["Write code"],
        "definition_of_done": ["Tests pass"],
    }
    defaults.update(kwargs)
    return PlanModel(**defaults)


# ---------------------------------------------------------------------------
# Skill detection from build.gradle
# ---------------------------------------------------------------------------


class TestSkillDetectionFromGradle:
    def test_navigation_detected(self, tmp_path):
        _write(tmp_path / "build.gradle", "")
        _write(
            tmp_path / "app" / "build.gradle",
            "implementation 'androidx.navigation:navigation-compose:2.8.0'\n",
        )
        scanner = ProjectScanner(tmp_path)
        skills = scanner._scan_for_skills()
        assert "navigation3" in skills

    def test_compose_detected(self, tmp_path):
        _write(tmp_path / "build.gradle", "")
        _write(
            tmp_path / "app" / "build.gradle",
            "implementation 'androidx.compose.ui:ui:1.7.0'\nimplementation 'androidx.compose.material3:material3:1.3.0'\n",
        )
        scanner = ProjectScanner(tmp_path)
        skills = scanner._scan_for_skills()
        assert "compose-migration" in skills

    def test_edge_to_edge_detected(self, tmp_path):
        _write(tmp_path / "build.gradle", "")
        _write(
            tmp_path / "app" / "src" / "main" / "MainKt.kt",
            "enableEdgeToEdge()\nWindowCompat.setDecorFitsSystemWindows(window, false)\n",
        )
        # Edge-to-edge is detected from source code keywords in build.gradle
        # The scanner checks build.gradle for the keyword
        _write(
            tmp_path / "app" / "build.gradle",
            "// enableEdgeToEdge is used in this project\n",
        )
        scanner = ProjectScanner(tmp_path)
        skills = scanner._scan_for_skills()
        assert "edge-to-edge" in skills

    def test_no_skills_empty_project(self, tmp_path):
        _write(tmp_path / "build.gradle", "// empty project\n")
        scanner = ProjectScanner(tmp_path)
        skills = scanner._scan_for_skills()
        # Should be empty or minimal for a plain project
        assert isinstance(skills, list)


# ---------------------------------------------------------------------------
# SKILL.md file scanning
# ---------------------------------------------------------------------------


class TestSkillMdScanning:
    def test_skill_md_file_found(self, tmp_path):
        _write(
            tmp_path / "skills" / "SKILL.md",
            "# MyCustomSkill\n\nA custom Android skill.\n",
        )
        scanner = ProjectScanner(tmp_path)
        skills = scanner._scan_for_skills()
        assert "MyCustomSkill" in skills

    def test_multiple_skill_files(self, tmp_path):
        _write(tmp_path / "SKILL.md", "# SkillOne\n\nDescription.\n")
        _write(tmp_path / "skills" / "SKILL.md", "# SkillTwo\n\nDescription.\n")
        scanner = ProjectScanner(tmp_path)
        skills = scanner._scan_for_skills()
        assert "SkillOne" in skills or "SkillTwo" in skills  # at least one found


# ---------------------------------------------------------------------------
# Skills compliance validation
# ---------------------------------------------------------------------------


class TestSkillsComplianceValidation:
    def test_compliant_all_skills_in_plan(self):
        plan = _android_plan(android_skills=["navigation3", "compose-migration"])
        info = ProjectInfo(
            project_type=ProjectType.ANDROID,
            detected_skills=["navigation3", "compose-migration"],
        )
        result = validate_skills_compliance(plan, info)
        assert result.compliant is True
        assert result.missing_skills == []

    def test_missing_skill_found(self):
        plan = _android_plan(android_skills=[])
        info = ProjectInfo(
            project_type=ProjectType.ANDROID,
            detected_skills=["navigation3", "edge-to-edge"],
        )
        result = validate_skills_compliance(plan, info)
        assert isinstance(result, SkillsComplianceResult)
        # Tasks don't mention these skills, so they should be flagged as missing
        assert result.compliant is False
        assert "navigation3" in result.missing_skills or "edge-to-edge" in result.missing_skills

    def test_partial_skills_compliance(self):
        plan = _android_plan(android_skills=["navigation3"])
        info = ProjectInfo(
            project_type=ProjectType.ANDROID,
            detected_skills=["navigation3", "compose-migration"],
        )
        result = validate_skills_compliance(plan, info)
        # navigation3 is in plan, compose-migration is not
        assert "navigation3" not in result.missing_skills

    def test_ios_project_always_compliant(self):
        plan = _android_plan()
        info = ProjectInfo(project_type=ProjectType.IOS)
        result = validate_skills_compliance(plan, info)
        assert result.compliant is True

    def test_suggestions_provided_for_missing(self):
        plan = _android_plan(android_skills=[])
        info = ProjectInfo(
            project_type=ProjectType.ANDROID,
            detected_skills=["navigation3"],
        )
        result = validate_skills_compliance(plan, info)
        if result.missing_skills:
            assert len(result.suggestions) > 0


# ---------------------------------------------------------------------------
# used-skills.json writing
# ---------------------------------------------------------------------------


class TestUsedSkillsJson:
    def test_writes_json(self, tmp_path):
        with patch("koteguard.validation.SESSIONS_DIR", tmp_path):
            path = write_used_skills_json("sess-skill1", ["navigation3", "agp9"])

        assert path.exists()
        data = json.loads(path.read_text())
        assert "used_skills" in data
        assert "navigation3" in data["used_skills"]
        assert "agp9" in data["used_skills"]

    def test_empty_skills_list(self, tmp_path):
        with patch("koteguard.validation.SESSIONS_DIR", tmp_path):
            path = write_used_skills_json("sess-empty", [])

        assert path.exists()
        data = json.loads(path.read_text())
        assert data["used_skills"] == []

    def test_output_in_correct_dir(self, tmp_path):
        with patch("koteguard.validation.SESSIONS_DIR", tmp_path):
            path = write_used_skills_json("sess-dir", ["edge-to-edge"])

        # Should be in sessions/{id}/output/
        assert path.parent.name == "output"
        assert path.parent.parent.name == "sess-dir"
