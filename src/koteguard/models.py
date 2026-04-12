"""Pydantic v2 models for KoteGuard."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ProjectType(str, Enum):
    ANDROID = "android"
    IOS = "ios"
    FLUTTER = "flutter"
    REACT_NATIVE = "react_native"
    MONOREPO = "monorepo"
    UNKNOWN = "unknown"


class SessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    DISCARDED = "discarded"
    PENDING_REVIEW = "pending_review"


class IDEChoice(str, Enum):
    ANDROID_STUDIO = "android"
    XCODE = "ios"
    AUTO = "auto"


# ---------------------------------------------------------------------------
# Task / Plan / Workspace models
# ---------------------------------------------------------------------------


class TaskModel(BaseModel):
    """Represents a single agent task."""

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
    """Represents the contents of a PLAN.md file."""

    title: str = Field(..., min_length=1)
    objectives: list[str] = Field(..., min_length=1)
    tasks: list[str] = Field(..., min_length=1)
    definition_of_done: list[str] = Field(..., min_length=1)
    estimated_time: str = Field(default="unknown")
    risks: list[str] = Field(default_factory=list)

    @field_validator("objectives", "tasks", "definition_of_done", mode="before")
    @classmethod
    def non_empty_list(cls, v: Any) -> list[str]:
        if isinstance(v, list) and len(v) == 0:
            raise ValueError("list must not be empty")
        return v


class WorkspaceModel(BaseModel):
    """Represents the contents of a WORKSPACE.md file."""

    project_name: str = Field(..., min_length=1)
    tech_stack: list[str] = Field(..., min_length=1)
    architecture: str = Field(default="")
    conventions: list[str] = Field(default_factory=list)
    structure: dict[str, str] = Field(default_factory=dict)
    gotchas: list[str] = Field(default_factory=list)


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
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    completed_at: datetime | None = None
    plan_title: str = ""
    ide: IDEChoice = IDEChoice.AUTO

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

    # Flutter-specific
    flutter_sdk: str | None = None

    # General
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    has_tests: bool = False
    has_ci: bool = False
    sub_projects: list[str] = Field(default_factory=list)
    elapsed_ms: float = 0.0

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# Audit log entry
# ---------------------------------------------------------------------------


class AuditEntry(BaseModel):
    """A single JSONL audit-log record."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
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

    model_config = {"arbitrary_types_allowed": True, "use_enum_values": True}


class ProjectLocalConfig(BaseModel):
    """Per-project .kote/local.toml schema (git-ignored)."""

    last_session_id: str | None = None
    default_ide: IDEChoice | None = None
    notes: str = ""

    model_config = {"use_enum_values": True}
