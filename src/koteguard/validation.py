"""Phase 5 – Validation and audit utilities."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from koteguard.config import read_audit_log
from koteguard.models import PlanModel, WorkspaceModel
from koteguard.planning import parse_plan


# ---------------------------------------------------------------------------
# PLAN.md validation
# ---------------------------------------------------------------------------


class ValidationResult:
    """Holds the outcome of a validation check."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.is_valid: bool = True

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.is_valid = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def __bool__(self) -> bool:
        return self.is_valid


def validate_plan_file(plan_path: Path) -> ValidationResult:
    """Parse and validate a PLAN.md file against the PlanModel schema."""
    result = ValidationResult()

    if not plan_path.exists():
        result.add_error(f"PLAN.md not found at {plan_path}")
        return result

    markdown = plan_path.read_text(encoding="utf-8")
    if not markdown.strip():
        result.add_error("PLAN.md is empty")
        return result

    try:
        plan = parse_plan(markdown)
    except Exception as exc:
        result.add_error(f"Failed to parse PLAN.md: {exc}")
        return result

    try:
        PlanModel.model_validate(plan.model_dump())
    except ValidationError as exc:
        for err in exc.errors():
            result.add_error(f"Schema error: {err['loc']} – {err['msg']}")

    # Semantic checks
    if plan.title in ("Untitled Plan", ""):
        result.add_warning("Plan has no meaningful title")

    placeholder_tasks = [t for t in plan.tasks if t.strip() in ("(none)", "")]
    if placeholder_tasks:
        result.add_warning("Plan contains placeholder tasks – fill them in")

    if plan.estimated_time in ("unknown", ""):
        result.add_warning("No estimated time provided")

    return result


def validate_workspace_file(workspace_path: Path) -> ValidationResult:
    """Parse and validate a WORKSPACE.md file."""
    result = ValidationResult()

    if not workspace_path.exists():
        result.add_error(f"WORKSPACE.md not found at {workspace_path}")
        return result

    markdown = workspace_path.read_text(encoding="utf-8")
    if not markdown.strip():
        result.add_error("WORKSPACE.md is empty")
        return result

    # Extract project_name from H1
    m = re.search(r"^#\s+WORKSPACE:\s*(.+)$", markdown, re.MULTILINE)
    if not m:
        result.add_error("WORKSPACE.md must start with '# WORKSPACE: <name>'")
        return result

    project_name = m.group(1).strip()

    # Extract tech stack list
    tech_stack = _extract_list_section(markdown, "Tech Stack")
    if not tech_stack:
        result.add_warning("No Tech Stack section found in WORKSPACE.md")
        tech_stack = ["unknown"]

    try:
        WorkspaceModel.model_validate(
            {
                "project_name": project_name,
                "tech_stack": tech_stack,
            }
        )
    except ValidationError as exc:
        for err in exc.errors():
            result.add_error(f"Schema error: {err['loc']} – {err['msg']}")

    return result


def _extract_list_section(markdown: str, section: str) -> list[str]:
    pattern = rf"##\s+{re.escape(section)}\s*\n(.*?)(?=^##|\Z)"
    m = re.search(pattern, markdown, re.MULTILINE | re.DOTALL)
    if not m:
        return []
    block = m.group(1)
    items: list[str] = []
    for line in block.splitlines():
        line = line.strip()
        m2 = re.match(r"^[-*•]\s+(.+)$", line)
        if m2:
            items.append(m2.group(1))
    return items


# ---------------------------------------------------------------------------
# Change validation against PLAN.md tasks
# ---------------------------------------------------------------------------


def validate_changes_against_plan(
    worktree_path: Path,
    plan_path: Path,
    changed_files: list[str],
) -> ValidationResult:
    """
    Compare actual changed files in the worktree against the tasks in PLAN.md.

    This is a heuristic check – it warns when changes seem out of scope.
    Returns a ValidationResult where ``is_valid`` may still be True even when
    warnings are present (warnings do not block acceptance, errors do).
    """
    result = ValidationResult()

    plan_result = validate_plan_file(plan_path)
    if not plan_result:
        result.add_error("PLAN.md is invalid – fix it first")
        return result

    plan = parse_plan(plan_path.read_text(encoding="utf-8"))

    # Collect keywords from tasks
    task_keywords: set[str] = set()
    for task in plan.tasks:
        words = re.findall(r"\b[a-zA-Z]{3,}\b", task.lower())
        task_keywords.update(words)

    # Heuristic: warn on test/ci file changes if not mentioned
    suspicious_patterns = [
        (r"\.github/workflows/", "CI workflow changes"),
        (r"Podfile\.lock$", "Podfile.lock changes (dependency lock)"),
        (r"package-lock\.json$", "package-lock.json changes"),
    ]
    for pattern, label in suspicious_patterns:
        matching = [f for f in changed_files if re.search(pattern, f)]
        if matching:
            result.add_warning(
                f"Unexpected {label} – verify these are intentional: {matching}"
            )

    if not changed_files:
        result.add_warning("No changed files detected in worktree")

    return result


# ---------------------------------------------------------------------------
# Audit log summary
# ---------------------------------------------------------------------------


def summarise_audit(session_id: str | None = None) -> list[dict[str, Any]]:
    """Return audit log entries, optionally filtered by session_id."""
    entries = read_audit_log()
    if session_id:
        entries = [e for e in entries if e.get("session_id") == session_id]
    return entries
