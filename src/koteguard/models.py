"""Pydantic v2 models for KoteGuard."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ProjectType(StrEnum):
    ANDROID = "android"
    IOS = "ios"
    MONOREPO = "monorepo"
    UNKNOWN = "unknown"


class SessionStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    DISCARDED = "discarded"
    PENDING_REVIEW = "pending_review"


class IDEChoice(StrEnum):
    ANDROID_STUDIO = "android"
    XCODE = "ios"
    AUTO = "auto"


class AgentMode(StrEnum):
    """How the Copilot agent is invoked for a session."""

    COPILOT_CLI = "copilot-cli"       # terminal: copilot binary with deny-tool flags
    COPILOT_PLUGIN = "copilot-plugin"  # IDE plugin: no CLI command generated
    NONE = "none"                      # instructions injected only, no tool launched


# ---------------------------------------------------------------------------
# Task / Plan / Workspace models
# ---------------------------------------------------------------------------


class PlanTask(BaseModel):
    """A single task within a PLAN.md, tracked as a spec item."""

    id: str = Field(..., description="Auto-generated task ID, e.g. 't1', 't2'")
    description: str = Field(..., min_length=1, description="What must be done")
    done: bool = Field(default=False, description="Set to true by the agent when complete")


class TaskModel(BaseModel):
    """Represents a single agent task (TASK.md document)."""

    session_id: str = Field(..., description="Unique session identifier")
    description: str = Field(..., min_length=1, description="What the agent must do")
    context: str = Field(default="", description="Extra context for the agent")
    constraints: list[str] = Field(
        default_factory=list, description="Rules the agent must follow"
    )

    @field_validator("session_id")
    @classmethod
    def session_id_slug(cls, v: str) -> str:
        if not re.match(r"^[a-z0-9][a-z0-9\-]{2,}$", v):
            raise ValueError(
                "session_id must be lowercase alphanumeric with hyphens (min 3 chars)"
            )
        return v


class PlanModel(BaseModel):
    """Represents the contents of a PLAN.md file (source of truth spec)."""

    spec_version: str = Field(default="1.0", description="KoteGuard spec format version")
    title: str = Field(..., min_length=1)
    objectives: list[str] = Field(..., min_length=1)
    tasks: list[PlanTask] = Field(..., min_length=1)
    definition_of_done: list[str] = Field(..., min_length=1)
    estimated_time: str = Field(default="unknown")
    risks: list[str] = Field(default_factory=list)
    android_skills: list[str] = Field(default_factory=list)

    @field_validator("objectives", "definition_of_done", mode="before")
    @classmethod
    def non_empty_list(cls, v: Any) -> Any:
        if isinstance(v, list) and len(v) == 0:
            raise ValueError("list must not be empty")
        return v

    @field_validator("tasks", mode="before")
    @classmethod
    def non_empty_tasks(cls, v: Any) -> Any:
        if isinstance(v, list) and len(v) == 0:
            raise ValueError("tasks list must not be empty")
        # Accept list[str] (legacy) and coerce to list[PlanTask] dicts
        coerced = []
        for i, item in enumerate(v, 1):
            if isinstance(item, str):
                coerced.append({"id": f"t{i}", "description": item, "done": False})
            else:
                coerced.append(item)
        return coerced


class WorkspaceModel(BaseModel):
    """Represents the contents of a WORKSPACE.md file."""

    project_name: str = Field(..., min_length=1)
    tech_stack: list[str] = Field(..., min_length=1)
    architecture: str = Field(default="")
    conventions: list[str] = Field(default_factory=list)
    structure: dict[str, str] = Field(default_factory=dict)
    gotchas: list[str] = Field(default_factory=list)
    android_agent_stack: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Session metadata
# ---------------------------------------------------------------------------


class SessionMeta(BaseModel):
    """Persisted session metadata stored in ~/.kote/sessions/<id>/meta.json."""

    session_id: str
    project_slug: str
    project_root: Path
    worktree_path: Path
    branch_name: str
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    completed_at: datetime | None = None
    plan_title: str = ""
    ide: IDEChoice = IDEChoice.AUTO
    agent_mode: AgentMode = AgentMode.COPILOT_CLI
    android_cli_available: bool = False
    skills_loaded: list[str] = Field(default_factory=list)

    model_config = {"use_enum_values": True}


# ---------------------------------------------------------------------------
# Project analysis result
# ---------------------------------------------------------------------------


class ProjectInfo(BaseModel):
    """Result of Phase 0 project analysis."""

    project_type: ProjectType = ProjectType.UNKNOWN
    project_name: str = "unknown"
    root: Path = Field(default_factory=Path.cwd)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # Android-specific
    android_package: str | None = None
    android_min_sdk: int | None = None
    android_target_sdk: int | None = None
    android_compile_sdk: int | None = None

    # iOS-specific
    ios_bundle_id: str | None = None
    ios_deployment_target: str | None = None

    # General
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    has_tests: bool = False
    has_ci: bool = False
    sub_projects: list[str] = Field(default_factory=list)
    elapsed_ms: float = 0.0

    # Android v1.1 additions
    android_cli_available: bool = False
    detected_skills: list[str] = Field(default_factory=list)
    knowledge_base_status: str = "unknown"
    doc_summary: dict[str, list[str]] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# Android Skills models (v1.1)
# ---------------------------------------------------------------------------


class AndroidSkillRef(BaseModel):
    """Reference to an Android agent skill."""

    name: str
    url: str
    enabled: bool = True
    description: str = ""


class UsedSkill(BaseModel):
    """Records a skill that was applied during a session."""

    skill_name: str
    applied_to: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class SkillsComplianceResult(BaseModel):
    """Result of a skills compliance check."""

    compliant: bool
    missing_skills: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Audit log entry
# ---------------------------------------------------------------------------


class AuditEntry(BaseModel):
    """A single JSONL audit-log record."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    event: str
    session_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    model_config = {"use_enum_values": True}


# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------


class GlobalConfig(BaseModel):
    """~/.kote/config.toml schema."""

    default_ide: IDEChoice = IDEChoice.AUTO
    worktrees_dir: Path = Field(
        default_factory=lambda: Path.home() / ".kote" / "worktrees"
    )
    sessions_dir: Path = Field(
        default_factory=lambda: Path.home() / ".kote" / "sessions"
    )
    audit_log: Path = Field(
        default_factory=lambda: Path.home() / ".kote" / "audit.jsonl"
    )
    auto_open_ide: bool = True
    android_cli_version: str = ""
    skills_repo_url: str = "https://github.com/android/skills"
    agent_mode: AgentMode = AgentMode.COPILOT_CLI
    android_cli_enabled: bool = True

    model_config = {"arbitrary_types_allowed": True, "use_enum_values": True}


class ProjectLocalConfig(BaseModel):
    """Per-project .kote/local.toml schema (git-ignored)."""

    last_session_id: str | None = None
    default_ide: IDEChoice | None = None
    notes: str = ""
    android_cli_enabled: bool | None = None  # None = defer to GlobalConfig

    model_config = {"use_enum_values": True}
