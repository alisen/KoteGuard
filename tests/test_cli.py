"""CLI integration tests using Typer's CliRunner.

These tests exercise real CLI entry points without needing a git repository.
Commands tested: version, validate, status (no sessions), android skills, ios skills.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from koteguard.cli import app
from koteguard.templates import _templates_dir, get_template, list_templates

runner = CliRunner()


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------


def test_version_prints_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "KoteGuard" in result.output
    assert "v" in result.output


# ---------------------------------------------------------------------------
# status (no sessions)
# ---------------------------------------------------------------------------


def test_status_no_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    """kote status should exit 0 and print a message when there are no sessions."""
    monkeypatch.setattr("koteguard.worktree.SESSIONS_DIR", Path("/tmp/kote-nonexistent-dir"))
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "No sessions" in result.output


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_missing_file(tmp_path: Path) -> None:
    """kote validate on a non-existent file should exit 1 with an error."""
    plan_path = tmp_path / "PLAN.md"
    result = runner.invoke(app, ["validate", str(plan_path)])
    assert result.exit_code == 1
    assert "not found" in result.output.lower() or "FAILED" in result.output


def test_validate_valid_plan(tmp_path: Path) -> None:
    """kote validate on a well-formed PLAN.md should exit 0."""
    from koteguard.models import PlanModel
    from koteguard.planning import render_plan

    plan = PlanModel(
        title="Test Plan",
        objectives=["Implement feature"],
        tasks=["Write code", "Write tests"],
        definition_of_done=["All tests pass"],
        estimated_time="1 hour",
    )
    plan_path = tmp_path / "PLAN.md"
    plan_path.write_text(render_plan(plan), encoding="utf-8")

    result = runner.invoke(app, ["validate", str(plan_path)])
    assert result.exit_code == 0
    assert "valid" in result.output.lower()


def test_validate_workspace_failure_exits_1(tmp_path: Path) -> None:
    """kote validate -w with a bad WORKSPACE.md should exit 1."""
    from koteguard.models import PlanModel
    from koteguard.planning import render_plan

    plan = PlanModel(
        title="Test Plan",
        objectives=["Implement feature"],
        tasks=["Write code"],
        definition_of_done=["Tests pass"],
        estimated_time="1 hour",
    )
    plan_path = tmp_path / "PLAN.md"
    plan_path.write_text(render_plan(plan), encoding="utf-8")

    ws_path = tmp_path / "WORKSPACE.md"
    ws_path.write_text("# Bad workspace — missing required header\n", encoding="utf-8")

    result = runner.invoke(app, ["validate", str(plan_path), "-w", str(ws_path)])
    assert result.exit_code == 1


def test_validate_both_pass(tmp_path: Path) -> None:
    """kote validate -w with valid plan and workspace should exit 0."""
    from koteguard.models import PlanModel, WorkspaceModel
    from koteguard.planning import render_plan, render_workspace

    plan = PlanModel(
        title="Test Plan",
        objectives=["Implement feature"],
        tasks=["Write code"],
        definition_of_done=["Tests pass"],
        estimated_time="1 hour",
    )
    ws = WorkspaceModel(project_name="MyApp", tech_stack=["Kotlin", "Android SDK"])

    plan_path = tmp_path / "PLAN.md"
    plan_path.write_text(render_plan(plan), encoding="utf-8")
    ws_path = tmp_path / "WORKSPACE.md"
    ws_path.write_text(render_workspace(ws), encoding="utf-8")

    result = runner.invoke(app, ["validate", str(plan_path), "-w", str(ws_path)])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# android skills
# ---------------------------------------------------------------------------


def test_android_skills_lists_skills(tmp_path: Path) -> None:
    """kote android skills should exit 0 and list at least one skill."""
    result = runner.invoke(app, ["android", "skills", "--project", str(tmp_path)])
    assert result.exit_code == 0
    # Should show the skills table header or at least one known skill name
    output = result.output
    assert any(
        skill in output
        for skill in ["navigation3", "edge-to-edge", "agp9", "compose-migration", "Android Skills"]
    )


# ---------------------------------------------------------------------------
# ios skills
# ---------------------------------------------------------------------------


def test_ios_skills_lists_skills(tmp_path: Path) -> None:
    """kote ios skills should exit 0 and list iOS skill entries."""
    result = runner.invoke(app, ["ios", "skills", "--project", str(tmp_path)])
    assert result.exit_code == 0
    output = result.output
    assert any(
        skill in output
        for skill in ["swiftui-patterns", "swift-concurrency", "xctest", "iOS Skills"]
    )


# ---------------------------------------------------------------------------
# sessions prune (dry-run, no sessions)
# ---------------------------------------------------------------------------


def test_sessions_prune_no_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    """kote sessions prune --dry-run with no sessions should exit 0 gracefully."""
    monkeypatch.setattr("koteguard.worktree.SESSIONS_DIR", Path("/tmp/kote-nonexistent-dir"))
    result = runner.invoke(app, ["sessions", "prune", "--dry-run"])
    assert result.exit_code == 0
    assert "No completed" in result.output or "0 session" in result.output or "No " in result.output


# ---------------------------------------------------------------------------
# templates module
# ---------------------------------------------------------------------------


def test_templates_dir_exists() -> None:
    d = _templates_dir()
    assert d.exists()
    assert d.is_dir()


def test_list_templates_non_empty() -> None:
    names = list_templates()
    assert len(names) > 0
    assert any(n.endswith(".md") for n in names)


def test_get_template_plan_md() -> None:
    content = get_template("PLAN.md")
    assert len(content) > 0


def test_get_template_missing_raises() -> None:
    with pytest.raises(FileNotFoundError):
        get_template("nonexistent-template-xyz.md")


# ---------------------------------------------------------------------------
# config module
# ---------------------------------------------------------------------------


def test_resolve_android_cli_enabled_returns_bool(tmp_path: Path) -> None:
    from koteguard.config import resolve_android_cli_enabled

    # On a temp path (no .kote/local.toml) it should fall through to global config
    result = resolve_android_cli_enabled(tmp_path)
    assert isinstance(result, bool)


def test_project_kote_dir(tmp_path: Path) -> None:
    from koteguard.config import project_kote_dir

    result = project_kote_dir(tmp_path)
    assert result == tmp_path / ".kote"


def test_ensure_project_gitignore_adds_entries(tmp_path: Path) -> None:
    from koteguard.config import ensure_project_gitignore

    ensure_project_gitignore(tmp_path)
    gi_path = tmp_path / ".gitignore"
    assert gi_path.exists()
    content = gi_path.read_text(encoding="utf-8")
    assert ".kote/local.toml" in content
    assert ".kote/history/" in content


def test_ensure_project_gitignore_idempotent(tmp_path: Path) -> None:
    from koteguard.config import ensure_project_gitignore

    ensure_project_gitignore(tmp_path)
    ensure_project_gitignore(tmp_path)  # second call should not duplicate
    content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert content.count(".kote/local.toml") == 1
