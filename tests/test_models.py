"""Comprehensive tests for koteguard/models.py.

Covers every model, enum, validator, and field constraint.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from koteguard.models import (
    AgentMode,
    AndroidSkillRef,
    AuditEntry,
    GlobalConfig,
    IDEChoice,
    PlanModel,
    PlanTask,
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
# Enums
# ---------------------------------------------------------------------------


class TestProjectType:
    def test_values(self):
        assert ProjectType.ANDROID == "android"
        assert ProjectType.IOS == "ios"
        assert ProjectType.MONOREPO == "monorepo"
        assert ProjectType.UNKNOWN == "unknown"

    def test_str_enum(self):
        assert str(ProjectType.ANDROID) == "android"

    def test_membership(self):
        assert "android" in list(ProjectType)
        assert "ios" in list(ProjectType)


class TestSessionStatus:
    def test_all_values(self):
        assert SessionStatus.ACTIVE == "active"
        assert SessionStatus.COMPLETED == "completed"
        assert SessionStatus.DISCARDED == "discarded"
        assert SessionStatus.PENDING_REVIEW == "pending_review"


class TestIDEChoice:
    def test_values(self):
        assert IDEChoice.ANDROID_STUDIO == "android"
        assert IDEChoice.XCODE == "ios"
        assert IDEChoice.AUTO == "auto"


class TestAgentMode:
    def test_values(self):
        assert AgentMode.COPILOT_CLI == "copilot-cli"
        assert AgentMode.COPILOT_PLUGIN == "copilot-plugin"
        assert AgentMode.NONE == "none"

    def test_from_string(self):
        assert AgentMode("copilot-cli") == AgentMode.COPILOT_CLI

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            AgentMode("bad-mode")


# ---------------------------------------------------------------------------
# PlanTask
# ---------------------------------------------------------------------------


class TestPlanTask:
    def test_basic(self):
        t = PlanTask(id="t1", description="Do something")
        assert t.id == "t1"
        assert t.done is False

    def test_done_true(self):
        t = PlanTask(id="t2", description="Done task", done=True)
        assert t.done is True

    def test_empty_description_raises(self):
        with pytest.raises(ValidationError):
            PlanTask(id="t3", description="")


# ---------------------------------------------------------------------------
# TaskModel
# ---------------------------------------------------------------------------


class TestTaskModel:
    def test_valid(self):
        t = TaskModel(
            session_id="abc-123",
            description="Fix the bug",
            context="Some context",
            constraints=["No push"],
        )
        assert t.session_id == "abc-123"
        assert t.constraints == ["No push"]

    def test_default_context_and_constraints(self):
        t = TaskModel(session_id="abc-123", description="Task")
        assert t.context == ""
        assert t.constraints == []

    def test_invalid_session_id_too_short(self):
        with pytest.raises(ValidationError):
            TaskModel(session_id="ab", description="Task")

    def test_invalid_session_id_uppercase(self):
        with pytest.raises(ValidationError):
            TaskModel(session_id="ABC-def", description="Task")

    def test_invalid_session_id_starts_with_dash(self):
        with pytest.raises(ValidationError):
            TaskModel(session_id="-abc-123", description="Task")

    def test_empty_description_raises(self):
        with pytest.raises(ValidationError):
            TaskModel(session_id="abc-123", description="")


# ---------------------------------------------------------------------------
# PlanModel
# ---------------------------------------------------------------------------


class TestPlanModel:
    def test_valid_basic(self):
        plan = PlanModel(
            title="My Plan",
            objectives=["Do something"],
            tasks=["Task 1"],
            definition_of_done=["All done"],
        )
        assert plan.title == "My Plan"
        assert len(plan.tasks) == 1
        assert isinstance(plan.tasks[0], PlanTask)

    def test_tasks_coerced_from_strings(self):
        plan = PlanModel(
            title="Plan",
            objectives=["Obj"],
            tasks=["First", "Second"],
            definition_of_done=["Done"],
        )
        assert plan.tasks[0].id == "t1"
        assert plan.tasks[0].description == "First"
        assert plan.tasks[1].id == "t2"

    def test_tasks_as_plan_task_objects(self):
        plan = PlanModel(
            title="Plan",
            objectives=["Obj"],
            tasks=[PlanTask(id="x1", description="desc", done=True)],
            definition_of_done=["Done"],
        )
        assert plan.tasks[0].id == "x1"
        assert plan.tasks[0].done is True

    def test_empty_title_raises(self):
        with pytest.raises(ValidationError):
            PlanModel(
                title="",
                objectives=["Obj"],
                tasks=["Task"],
                definition_of_done=["Done"],
            )

    def test_empty_objectives_raises(self):
        with pytest.raises(ValidationError):
            PlanModel(
                title="Plan",
                objectives=[],
                tasks=["Task"],
                definition_of_done=["Done"],
            )

    def test_empty_tasks_raises(self):
        with pytest.raises(ValidationError):
            PlanModel(
                title="Plan",
                objectives=["Obj"],
                tasks=[],
                definition_of_done=["Done"],
            )

    def test_empty_definition_of_done_raises(self):
        with pytest.raises(ValidationError):
            PlanModel(
                title="Plan",
                objectives=["Obj"],
                tasks=["Task"],
                definition_of_done=[],
            )

    def test_android_skills_default_empty(self):
        plan = PlanModel(
            title="Plan",
            objectives=["Obj"],
            tasks=["Task"],
            definition_of_done=["Done"],
        )
        assert plan.android_skills == []

    def test_risks_default_empty(self):
        plan = PlanModel(
            title="Plan",
            objectives=["Obj"],
            tasks=["Task"],
            definition_of_done=["Done"],
        )
        assert plan.risks == []

    def test_spec_version_default(self):
        plan = PlanModel(
            title="Plan",
            objectives=["Obj"],
            tasks=["Task"],
            definition_of_done=["Done"],
        )
        assert plan.spec_version == "1.0"

    def test_estimated_time_default(self):
        plan = PlanModel(
            title="Plan",
            objectives=["Obj"],
            tasks=["Task"],
            definition_of_done=["Done"],
        )
        assert plan.estimated_time == "unknown"

    def test_full_plan(self):
        plan = PlanModel(
            title="Full Plan",
            objectives=["Obj 1", "Obj 2"],
            tasks=["Task A", "Task B", "Task C"],
            definition_of_done=["Tests pass", "Review done"],
            estimated_time="2 hours",
            risks=["Breaking change"],
            android_skills=["navigation3", "compose-migration"],
        )
        assert len(plan.tasks) == 3
        assert plan.risks == ["Breaking change"]
        assert plan.android_skills == ["navigation3", "compose-migration"]


# ---------------------------------------------------------------------------
# WorkspaceModel
# ---------------------------------------------------------------------------


class TestWorkspaceModel:
    def test_valid(self):
        ws = WorkspaceModel(project_name="MyApp", tech_stack=["Kotlin", "Gradle"])
        assert ws.project_name == "MyApp"
        assert ws.architecture == ""

    def test_empty_project_name_raises(self):
        with pytest.raises(ValidationError):
            WorkspaceModel(project_name="", tech_stack=["Kotlin"])

    def test_empty_tech_stack_raises(self):
        with pytest.raises(ValidationError):
            WorkspaceModel(project_name="App", tech_stack=[])

    def test_optional_fields_defaults(self):
        ws = WorkspaceModel(project_name="App", tech_stack=["Swift"])
        assert ws.conventions == []
        assert ws.structure == {}
        assert ws.gotchas == []
        assert ws.android_agent_stack == {}

    def test_full_workspace(self):
        ws = WorkspaceModel(
            project_name="BigApp",
            tech_stack=["Kotlin", "Compose"],
            architecture="MVVM",
            conventions=["Use coroutines"],
            structure={"app/src/": "Main source"},
            gotchas=["Don't commit .env"],
            android_agent_stack={"cli_version": "1.0"},
        )
        assert ws.architecture == "MVVM"
        assert "Use coroutines" in ws.conventions


# ---------------------------------------------------------------------------
# SessionMeta
# ---------------------------------------------------------------------------


class TestSessionMeta:
    def test_minimal(self, tmp_path):
        meta = SessionMeta(
            session_id="abc-1234",
            project_slug="myapp",
            project_root=tmp_path,
            worktree_path=tmp_path / "wt",
            branch_name="kote/abc-1234-task",
        )
        assert meta.status == "active"
        assert meta.android_cli_available is False
        assert meta.skills_loaded == []
        assert isinstance(meta.created_at, datetime)

    def test_status_progression(self, tmp_path):
        meta = SessionMeta(
            session_id="s1",
            project_slug="proj",
            project_root=tmp_path,
            worktree_path=tmp_path,
            branch_name="kote/s1-task",
            status=SessionStatus.COMPLETED,
        )
        assert meta.status == "completed"

    def test_use_enum_values(self, tmp_path):
        """model_config use_enum_values means status serializes as string."""
        meta = SessionMeta(
            session_id="s2",
            project_slug="p",
            project_root=tmp_path,
            worktree_path=tmp_path,
            branch_name="b",
        )
        dump = meta.model_dump(mode="json")
        assert isinstance(dump["status"], str)

    def test_plan_title_default_empty(self, tmp_path):
        meta = SessionMeta(
            session_id="s3",
            project_slug="p",
            project_root=tmp_path,
            worktree_path=tmp_path,
            branch_name="b",
        )
        assert meta.plan_title == ""


# ---------------------------------------------------------------------------
# ProjectInfo
# ---------------------------------------------------------------------------


class TestProjectInfo:
    def test_defaults(self):
        info = ProjectInfo()
        assert info.project_type == ProjectType.UNKNOWN
        assert info.project_name == "unknown"
        assert info.confidence == 0.0
        assert info.languages == []
        assert info.detected_skills == []
        assert info.ios_detected_skills == []

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            ProjectInfo(confidence=1.5)
        with pytest.raises(ValidationError):
            ProjectInfo(confidence=-0.1)

    def test_android_fields(self):
        info = ProjectInfo(
            project_type=ProjectType.ANDROID,
            android_min_sdk=26,
            android_target_sdk=34,
            android_compile_sdk=34,
            android_package="com.example.app",
        )
        assert info.android_min_sdk == 26
        assert info.android_package == "com.example.app"

    def test_ios_fields(self):
        info = ProjectInfo(
            project_type=ProjectType.IOS,
            ios_bundle_id="com.example.app",
            ios_deployment_target="16.0",
        )
        assert info.ios_bundle_id == "com.example.app"
        assert info.ios_deployment_target == "16.0"


# ---------------------------------------------------------------------------
# AndroidSkillRef
# ---------------------------------------------------------------------------


class TestAndroidSkillRef:
    def test_basic(self):
        ref = AndroidSkillRef(name="navigation3", url="https://example.com", enabled=True)
        assert ref.name == "navigation3"
        assert ref.description == ""

    def test_disabled(self):
        ref = AndroidSkillRef(name="agp9", url="https://example.com", enabled=False)
        assert ref.enabled is False


# ---------------------------------------------------------------------------
# UsedSkill
# ---------------------------------------------------------------------------


class TestUsedSkill:
    def test_defaults(self):
        skill = UsedSkill(skill_name="navigation3", applied_to="MainActivity.kt")
        assert isinstance(skill.timestamp, datetime)

    def test_custom_timestamp(self):
        ts = datetime(2024, 1, 1, tzinfo=UTC)
        skill = UsedSkill(skill_name="agp9", applied_to="build.gradle", timestamp=ts)
        assert skill.timestamp == ts


# ---------------------------------------------------------------------------
# SkillsComplianceResult
# ---------------------------------------------------------------------------


class TestSkillsComplianceResult:
    def test_compliant(self):
        r = SkillsComplianceResult(compliant=True)
        assert r.compliant is True
        assert r.missing_skills == []
        assert r.suggestions == []

    def test_non_compliant_with_details(self):
        r = SkillsComplianceResult(
            compliant=False,
            missing_skills=["navigation3"],
            suggestions=["Add navigation3 to android_skills"],
        )
        assert not r.compliant
        assert "navigation3" in r.missing_skills


# ---------------------------------------------------------------------------
# AuditEntry
# ---------------------------------------------------------------------------


class TestAuditEntry:
    def test_defaults(self):
        entry = AuditEntry(event="session_created")
        assert isinstance(entry.timestamp, datetime)
        assert entry.session_id is None
        assert entry.details == {}

    def test_full(self):
        entry = AuditEntry(
            event="worktree_accepted",
            session_id="abc-123",
            details={"branch": "kote/abc"},
        )
        assert entry.session_id == "abc-123"
        assert entry.details["branch"] == "kote/abc"


# ---------------------------------------------------------------------------
# GlobalConfig
# ---------------------------------------------------------------------------


class TestGlobalConfig:
    def test_defaults(self):
        cfg = GlobalConfig()
        assert cfg.default_ide == "auto"
        assert cfg.agent_mode == "copilot-cli"
        assert cfg.android_cli_enabled is True
        assert cfg.auto_open_ide is True
        assert cfg.skills_repo_url == "https://github.com/android/skills"

    def test_worktrees_dir_default(self):
        cfg = GlobalConfig()
        assert ".kote" in str(cfg.worktrees_dir)

    def test_override_agent_mode(self):
        cfg = GlobalConfig(agent_mode=AgentMode.COPILOT_PLUGIN)
        assert cfg.agent_mode == "copilot-plugin"

    def test_model_dump_json_mode(self):
        cfg = GlobalConfig()
        data = cfg.model_dump(mode="json")
        assert isinstance(data["default_ide"], str)
        assert isinstance(data["agent_mode"], str)


# ---------------------------------------------------------------------------
# ProjectLocalConfig
# ---------------------------------------------------------------------------


class TestProjectLocalConfig:
    def test_defaults(self):
        cfg = ProjectLocalConfig()
        assert cfg.last_session_id is None
        assert cfg.default_ide is None
        assert cfg.notes == ""
        assert cfg.android_cli_enabled is None

    def test_with_values(self):
        cfg = ProjectLocalConfig(
            last_session_id="abc-1",
            default_ide=IDEChoice.ANDROID_STUDIO,
            android_cli_enabled=False,
        )
        assert cfg.last_session_id == "abc-1"
        assert cfg.android_cli_enabled is False

    def test_dump_excludes_none(self):
        cfg = ProjectLocalConfig()
        data = cfg.model_dump(mode="json", exclude_none=True)
        assert "last_session_id" not in data
        assert "android_cli_enabled" not in data
