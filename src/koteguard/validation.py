"""Phase 5 – Validation and audit utilities."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from koteguard.config import SESSIONS_DIR, read_audit_log, read_session_audit
from koteguard.models import (
    PlanModel,
    ProjectInfo,
    SkillsComplianceResult,
    WorkspaceModel,
)
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

    if plan.title in ("Untitled Plan", ""):
        result.add_warning("Plan has no meaningful title")

    placeholder_tasks = [t for t in plan.tasks if t.description.strip() in ("(none)", "")]
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

    m = re.search(r"^#\s+WORKSPACE:\s*(.+)$", markdown, re.MULTILINE)
    if not m:
        result.add_error("WORKSPACE.md must start with '# WORKSPACE: <name>'")
        return result

    project_name = m.group(1).strip()
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


def _task_keywords(description: str) -> set[str]:
    """Extract keywords from a task description, splitting CamelCase words."""
    # Split CamelCase: "NavGraph" → ["Nav", "Graph"]
    spaced = re.sub(r"([A-Z])", r" \1", description)
    words = re.findall(r"[a-zA-Z]{3,}", spaced)
    return {w.lower() for w in words}


def _file_matches_task(file_path: str, keywords: set[str]) -> bool:
    """Return True if the file path contains any of the task keywords."""
    path_lower = file_path.lower()
    return any(kw in path_lower for kw in keywords)


def validate_changes_against_plan(
    worktree_path: Path,
    plan_path: Path,
    changed_files: list[str],
) -> ValidationResult:
    """Compare actual changed files against the tasks in PLAN.md."""
    result = ValidationResult()

    plan_result = validate_plan_file(plan_path)
    if not plan_result:
        result.add_error("PLAN.md is invalid – fix it first")
        return result

    plan = parse_plan(plan_path.read_text(encoding="utf-8"))

    if not changed_files:
        result.add_warning("No changed files detected in worktree")
        return result

    # Semantic matching: check each task against changed file paths
    for task in plan.tasks:
        keywords = _task_keywords(task.description)
        if keywords and not any(_file_matches_task(f, keywords) for f in changed_files):
            result.add_warning(
                f'Task `{task.id}` "{task.description}" has no matching changed files – '
                "verify work is complete"
            )

    # Check if agent updated any task as done
    all_undone = all(not t.done for t in plan.tasks)
    if all_undone and changed_files:
        result.add_warning(
            "All tasks still marked `done: false` in PLAN.md spec – "
            "the agent should set `done: true` for completed tasks"
        )

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

    return result


# ---------------------------------------------------------------------------
# Skills compliance (Android v1.1)
# ---------------------------------------------------------------------------


def validate_skills_compliance(
    plan: PlanModel,
    project_info: ProjectInfo,
) -> SkillsComplianceResult:
    """
    Check if plan tasks reference recommended Android skills.

    Returns a SkillsComplianceResult with missing skills and suggestions.
    """
    from koteguard.models import ProjectType

    if project_info.project_type not in (ProjectType.ANDROID, ProjectType.MONOREPO):
        return SkillsComplianceResult(compliant=True)

    recommended = set(project_info.detected_skills)
    referenced = set(plan.android_skills)

    # Also scan task text for skill name mentions
    task_descriptions = [t.description for t in plan.tasks]
    all_task_text = " ".join(task_descriptions + plan.objectives).lower()
    for skill in recommended:
        if skill.lower() in all_task_text:
            referenced.add(skill)

    missing = list(recommended - referenced)
    suggestions: list[str] = []

    for skill in missing:
        suggestions.append(
            f"Consider referencing skill '{skill}' in your PLAN.md android_skills list"
        )

    return SkillsComplianceResult(
        compliant=len(missing) == 0,
        missing_skills=missing,
        suggestions=suggestions,
    )


# ---------------------------------------------------------------------------
# Validation report
# ---------------------------------------------------------------------------


def render_validation_report(
    session_id: str,
    plan_result: ValidationResult,
    changes_result: ValidationResult,
    skills_result: SkillsComplianceResult | None,
    worktree_path: Path,
    plan_path: Path,
    created_at: datetime | None = None,
) -> str:
    """Render a complete validation-report.md."""
    now = datetime.now(tz=timezone.utc)
    lines: list[str] = [
        "# Validation Report",
        "",
        f"> Generated by KoteGuard on {now.strftime('%Y-%m-%d %H:%M UTC')}",
        f"> Session: `{session_id}`",
        "",
    ]

    # Plan Compliance
    plan_status = "✅ PASS" if plan_result.is_valid else "❌ FAIL"
    lines.append(f"## Plan Compliance: {plan_status}")
    lines.append("")
    if plan_result.errors:
        lines.append("### Errors")
        for e in plan_result.errors:
            lines.append(f"- ❌ {e}")
        lines.append("")
    if plan_result.warnings:
        lines.append("### Warnings")
        for w in plan_result.warnings:
            lines.append(f"- ⚠️ {w}")
        lines.append("")

    # Change Analysis
    changes_status = "✅ PASS" if changes_result.is_valid else "❌ FAIL"
    lines.append(f"## Change Analysis: {changes_status}")
    lines.append("")
    if changes_result.errors:
        lines.append("### Errors")
        for e in changes_result.errors:
            lines.append(f"- ❌ {e}")
        lines.append("")
    if changes_result.warnings:
        lines.append("### Warnings")
        for w in changes_result.warnings:
            lines.append(f"- ⚠️ {w}")
        lines.append("")

    # Skills Compliance
    if skills_result is not None:
        skills_status = "✅ PASS" if skills_result.compliant else "⚠️ SUGGESTIONS"
        lines.append(f"## Skills Compliance: {skills_status}")
        lines.append("")
        if skills_result.missing_skills:
            lines.append("### Missing Skills")
            for skill in skills_result.missing_skills:
                lines.append(f"- {skill}")
            lines.append("")
        if skills_result.suggestions:
            lines.append("### Suggestions")
            for s in skills_result.suggestions:
                lines.append(f"- {s}")
            lines.append("")

    # Used Android CLI Commands (from session audit)
    audit_entries = read_session_audit(session_id)
    android_cmds = [
        e for e in audit_entries if e.get("event") == "android_command"
    ]
    if android_cmds:
        lines.append("## Used Android CLI Commands")
        lines.append("")
        for entry in android_cmds:
            cmd = entry.get("details", {}).get("command", "unknown")
            ts = entry.get("timestamp", "")
            lines.append(f"- `{cmd}` at {ts}")
        lines.append("")

    # Token Hygiene Score
    lines.append("## Token Hygiene Score")
    lines.append("")

    session_age_str = "unknown"
    context_pressure = "Low"
    if created_at:
        age_seconds = (now - created_at).total_seconds()
        age_hours = age_seconds / 3600
        if age_hours < 1:
            session_age_str = f"{int(age_seconds / 60)}m"
        elif age_hours < 24:
            session_age_str = f"{age_hours:.1f}h"
        else:
            session_age_str = f"{age_hours / 24:.1f}d"

        if age_hours > 24:
            context_pressure = "High"
        elif age_hours > 4:
            context_pressure = "Medium"

    # Estimate context files
    context_files = []
    for fname in ("PLAN.md", "TASK.md", "WORKSPACE.md", "copilot-instructions.md"):
        candidate = worktree_path / fname
        if not candidate.exists():
            candidate = worktree_path / ".github" / fname
        if candidate.exists():
            context_files.append(fname)

    lines.append(f"- **Session Age:** {session_age_str}")
    lines.append(f"- **Context Files Injected:** {', '.join(context_files) if context_files else 'none detected'}")
    lines.append(f"- **Estimated Context Pressure:** {context_pressure}")

    recommendation = "Session looks healthy."
    if context_pressure == "High":
        recommendation = "Run `/compact` and summarize key decisions to WORKSPACE.md before next session."
    elif context_pressure == "Medium":
        recommendation = "Consider wrapping up soon to keep context fresh."

    lines.append(f"- **Recommendation:** {recommendation}")
    lines.append("")

    return "\n".join(lines)


def write_validation_report(
    session_id: str,
    content: str,
) -> Path:
    """Write validation-report.md to sessions/{id}/output/."""
    output_dir = SESSIONS_DIR / session_id / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "validation-report.md"
    report_path.write_text(content, encoding="utf-8")
    return report_path


def write_used_skills_json(session_id: str, skills: list[str]) -> Path:
    """Write used-skills.json to sessions/{id}/output/."""
    output_dir = SESSIONS_DIR / session_id / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    skills_path = output_dir / "used-skills.json"
    skills_path.write_text(
        json.dumps({"used_skills": skills}, indent=2), encoding="utf-8"
    )
    return skills_path


# ---------------------------------------------------------------------------
# Audit log summary
# ---------------------------------------------------------------------------


def summarise_audit(session_id: str | None = None) -> list[dict[str, Any]]:
    """Return audit log entries, optionally filtered by session_id."""
    entries = read_audit_log()
    if session_id:
        entries = [e for e in entries if e.get("session_id") == session_id]
    return entries
