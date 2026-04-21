"""Tests for Pydantic v2 models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from koteguard.models import (
    AndroidSkillRef,
    AuditEntry,
    GlobalConfig,
    IDEChoice,
    PlanModel,
    ProjectInfo,
    ProjectLocalConfig,
    ProjectType,
    SessionMeta,
    SessionStatus,
    SkillsComplianceResult,
    TaskModel,
    UsedSkill,
    WorkspaceModel,
)


# ---------------------------------------------------------------------------
# TaskModel
# ---------------------------------------------------------------------------


class TestTaskModel:
    def test_valid(self):
        t = TaskModel(
            session_id="abc-123",
            description="Add dark mode support",
            context="The app uses Material You",
            constraints=["Don't break existing tests"],
        )
        assert t.session_id == "abc-123"
        assert t.description == "Add dark mode support"

    def test_defaults(self):
        t = TaskModel(session_id="xyz-456", description="Fix bug")
        assert t.context == ""
        assert t.constraints == []

    def test_invalid_session_id_too_short(self):
        with pytest.raises(ValidationError):
            TaskModel(session_id="ab", description="x")

    def test_invalid_session_id_uppercase(self):
        with pytest.raises(ValidationError):
            TaskModel(session_id="ABC-def", description="x")

    def test_invalid_session_id_starts_with_dash(self):
        with pytest.raises(ValidationError):
            TaskModel(session_id="-abc-def", description="x")

    def test_empty_description_fails(self):
        with pytest.raises(ValidationError):
            TaskModel(session_id="abc-123", description="")


# ---------------------------------------------------------------------------
# PlanModel
# ---------------------------------------------------------------------------


class TestPlanModel:
    def test_valid(self):
        p = PlanModel(
            title="Add auth",
            objectives=["Implement login", "Implement logout"],
            tasks=["Create AuthViewModel", "Wire up UI"],
            definition_of_done=["Tests pass", "PR approved"],
            estimated_time="2 hours",
        )
        assert p.title == "Add auth"
        assert len(p.tasks) == 2

    def test_empty_objectives_fails(self):
        with pytest.raises(ValidationError):
            PlanModel(
                title="x",
                objectives=[],
                tasks=["t"],
                definition_of_done=["d"],
            )

    def test_empty_tasks_fails(self):
        with pytest.raises(ValidationError):
            PlanModel(
                title="x",
                objectives=["o"],
                tasks=[],
                definition_of_done=["d"],
            )

    def test_default_risks_empty(self):
        p = PlanModel(
            title="t",
            objectives=["o"],
            tasks=["t"],
            definition_of_done=["d"],
        )
        assert p.risks == []

    def test_default_estimated_time(self):
        p = PlanModel(
            title="t",
            objectives=["o"],
            tasks=["t"],
            definition_of_done=["d"],
        )
        assert p.estimated_time == "unknown"

    def test_android_skills_default_empty(self):
        p = PlanModel(
            title="t",
            objectives=["o"],
            tasks=["t"],
            definition_of_done=["d"],
        )
        assert p.android_skills == []

    def test_android_skills_populated(self):
        p = PlanModel(
            title="t",
            objectives=["o"],
            tasks=["t"],
            definition_of_done=["d"],
            android_skills=["navigation3", "edge-to-edge"],
        )
        assert "navigation3" in p.android_skills


# ---------------------------------------------------------------------------
# WorkspaceModel
# ---------------------------------------------------------------------------


class TestWorkspaceModel:
    def test_valid(self):
        ws = WorkspaceModel(
            project_name="MyApp",
            tech_stack=["Kotlin", "Android SDK"],
        )
        assert ws.project_name == "MyApp"
        assert "Kotlin" in ws.tech_stack

    def test_empty_tech_stack_fails(self):
        with pytest.raises(ValidationError):
            WorkspaceModel(project_name="x", tech_stack=[])

    def test_defaults(self):
        ws = WorkspaceModel(project_name="App", tech_stack=["Swift"])
        assert ws.architecture == ""
        assert ws.conventions == []
        assert ws.structure == {}
        assert ws.gotchas == []
        assert ws.android_agent_stack == {}

    def test_android_agent_stack(self):
        ws = WorkspaceModel(
            project_name="App",
            tech_stack=["Kotlin"],
            android_agent_stack={
                "cli_version": "available",
                "enabled_skills": ["navigation3"],
            },
        )
        assert ws.android_agent_stack["cli_version"] == "available"


# ---------------------------------------------------------------------------
# ProjectInfo
# ---------------------------------------------------------------------------


class TestProjectInfo:
    def test_defaults(self):
        pi = ProjectInfo()
        assert pi.project_type == ProjectType.UNKNOWN
        assert pi.confidence == 0.0
        assert pi.languages == []
        assert pi.android_cli_available is False
        assert pi.detected_skills == []
        assert pi.doc_summary == {}

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            ProjectInfo(confidence=1.5)
        with pytest.raises(ValidationError):
            ProjectInfo(confidence=-0.1)

    def test_android_type(self):
        pi = ProjectInfo(
            project_type=ProjectType.ANDROID,
            confidence=0.9,
            android_min_sdk=21,
        )
        assert pi.android_min_sdk == 21

    def test_no_flutter_rn_type(self):
        """Flutter and React Native should not exist as ProjectTypes."""
        valid_types = [pt.value for pt in ProjectType]
        assert "flutter" not in valid_types
        assert "react_native" not in valid_types

    def test_android_cli_available_field(self):
        pi = ProjectInfo(android_cli_available=True, detected_skills=["navigation3"])
        assert pi.android_cli_available is True
        assert "navigation3" in pi.detected_skills


# ---------------------------------------------------------------------------
# SessionMeta
# ---------------------------------------------------------------------------


class TestSessionMeta:
    def test_valid(self, tmp_path):
        meta = SessionMeta(
            session_id="sess-01",
            project_slug="my-app",
            project_root=tmp_path,
            worktree_path=tmp_path / "worktree",
            branch_name="kote/sess-01-task",
        )
        assert meta.status == "active"
        assert meta.completed_at is None
        assert meta.plan_title == ""
        assert meta.android_cli_available is False

    def test_status_enum_values(self, tmp_path):
        meta = SessionMeta(
            session_id="sess-02",
            project_slug="p",
            project_root=tmp_path,
            worktree_path=tmp_path,
            branch_name="b",
            status=SessionStatus.COMPLETED,
        )
        assert meta.status == "completed"

    def test_plan_title_field(self, tmp_path):
        meta = SessionMeta(
            session_id="sess-03",
            project_slug="p",
            project_root=tmp_path,
            worktree_path=tmp_path,
            branch_name="b",
            plan_title="Add login screen",
        )
        assert meta.plan_title == "Add login screen"

    def test_skills_loaded_field(self, tmp_path):
        meta = SessionMeta(
            session_id="sess-04",
            project_slug="p",
            project_root=tmp_path,
            worktree_path=tmp_path,
            branch_name="b",
            skills_loaded=["navigation3", "edge-to-edge"],
        )
        assert len(meta.skills_loaded) == 2


# ---------------------------------------------------------------------------
# GlobalConfig / ProjectLocalConfig
# ---------------------------------------------------------------------------


class TestGlobalConfig:
    def test_defaults(self):
        cfg = GlobalConfig()
        assert cfg.default_ide == "auto"
        assert cfg.auto_open_ide is True
        assert cfg.android_cli_version == ""
        assert cfg.skills_repo_url == "https://github.com/android/skills"

    def test_ide_choice(self):
        cfg = GlobalConfig(default_ide=IDEChoice.ANDROID_STUDIO)
        assert cfg.default_ide == "android"


class TestProjectLocalConfig:
    def test_defaults(self):
        cfg = ProjectLocalConfig()
        assert cfg.last_session_id is None
        assert cfg.notes == ""


# ---------------------------------------------------------------------------
# AuditEntry
# ---------------------------------------------------------------------------


class TestAuditEntry:
    def test_valid(self):
        e = AuditEntry(event="worktree_created", session_id="abc-123")
        assert e.event == "worktree_created"
        assert e.details == {}

    def test_with_details(self):
        e = AuditEntry(
            event="worktree_accepted",
            session_id="xyz",
            details={"branch": "kote/xyz-task"},
        )
        assert e.details["branch"] == "kote/xyz-task"


# ---------------------------------------------------------------------------
# Android Skills models (v1.1)
# ---------------------------------------------------------------------------


class TestAndroidSkillRef:
    def test_valid(self):
        skill = AndroidSkillRef(
            name="navigation3",
            url="https://developer.android.com/guide/navigation",
        )
        assert skill.name == "navigation3"
        assert skill.enabled is True
        assert skill.description == ""

    def test_disabled_skill(self):
        skill = AndroidSkillRef(
            name="agp9",
            url="https://example.com",
            enabled=False,
            description="AGP 9 migration",
        )
        assert skill.enabled is False


class TestUsedSkill:
    def test_valid(self):
        skill = UsedSkill(skill_name="navigation3", applied_to="HomeFragment.kt")
        assert skill.skill_name == "navigation3"
        assert skill.applied_to == "HomeFragment.kt"
        assert skill.timestamp is not None


class TestSkillsComplianceResult:
    def test_compliant(self):
        result = SkillsComplianceResult(compliant=True)
        assert result.compliant is True
        assert result.missing_skills == []
        assert result.suggestions == []

    def test_non_compliant(self):
        result = SkillsComplianceResult(
            compliant=False,
            missing_skills=["navigation3"],
            suggestions=["Add navigation3 to android_skills in PLAN.md"],
        )
        assert result.compliant is False
        assert len(result.missing_skills) == 1
