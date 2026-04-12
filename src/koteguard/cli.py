"""KoteGuard CLI – main Typer application."""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from koteguard import __version__

app = typer.Typer(
    name="kote",
    help="[bold green]KoteGuard[/] – safe Copilot agent sandboxing for mobile developers",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()
err_console = Console(stderr=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_git_repo(path: Path = Path.cwd()) -> Path:
    """Exit with an error if path is not inside a git repo."""
    import git

    try:
        repo = git.Repo(path, search_parent_directories=True)
        return Path(repo.working_tree_dir)
    except git.InvalidGitRepositoryError:
        err_console.print(
            "[bold red]Error:[/] Not inside a git repository. "
            "Run `git init` first."
        )
        raise typer.Exit(1)


def _print_banner() -> None:
    rprint(
        Panel(
            f"[bold green]KoteGuard[/] v{__version__}  –  "
            "[dim]Safe Copilot agent sandboxing for mobile developers[/]",
            style="green",
        )
    )


# ---------------------------------------------------------------------------
# prep – full interactive wizard
# ---------------------------------------------------------------------------


@app.command()
def prep(
    project: Annotated[
        Optional[Path],
        typer.Option("--project", "-p", help="Project root (default: cwd)"),
    ] = None,
    reconfigure: Annotated[
        bool,
        typer.Option("--reconfigure", help="Re-run Phase 0 project analysis"),
    ] = False,
    ide: Annotated[
        Optional[str],
        typer.Option("--ide", help="IDE override: android | ios"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would happen without doing it"),
    ] = False,
) -> None:
    """Full interactive wizard: analyse → plan → worktree → launch."""
    import questionary

    from koteguard.config import (
        ensure_project_gitignore,
        load_project_config,
        project_kote_dir,
        save_project_config,
    )
    from koteguard.launcher import IDELauncher, pick_ide
    from koteguard.models import IDEChoice, PlanModel
    from koteguard.planning import (
        render_copilot_instructions,
        render_plan,
        render_security_instructions,
        workspace_from_project_info,
        render_workspace,
    )
    from koteguard.project_scanner import ProjectScanner
    from koteguard.sensitive_files import SensitiveFileHandler
    from koteguard.worktree import WorktreeEngine

    _print_banner()
    project_root = _require_git_repo(project or Path.cwd())
    kote_dir = project_kote_dir(project_root)

    # ── Phase 0: Project analysis ────────────────────────────────────────
    console.print("\n[bold cyan]Phase 0:[/] Analysing project…")

    workspace_path = kote_dir / "WORKSPACE.md"
    workspace_exists = workspace_path.exists() and not reconfigure

    scanner = ProjectScanner(project_root)
    info = scanner.scan()

    console.print(
        f"  Detected: [bold]{info.project_type.value}[/] "
        f"(confidence {info.confidence:.0%})"
    )
    console.print(f"  Project name: [bold]{info.project_name}[/]")

    ws_model = workspace_from_project_info(info)

    if not workspace_exists:
        kote_dir.mkdir(parents=True, exist_ok=True)
        workspace_path.write_text(render_workspace(ws_model), encoding="utf-8")
        console.print(f"  Created [green]{workspace_path.relative_to(project_root)}[/]")
    else:
        console.print(f"  Using existing [dim]{workspace_path.relative_to(project_root)}[/]")

    ensure_project_gitignore(project_root)

    # ── Phase 1: Interactive planning ────────────────────────────────────
    console.print("\n[bold cyan]Phase 1:[/] Planning\n")

    plan_title = questionary.text("What should the agent do? (brief title)").ask()
    if not plan_title:
        err_console.print("[red]Cancelled.[/]")
        raise typer.Exit(0)

    objectives_raw = questionary.text(
        "List objectives (comma-separated)"
    ).ask()
    objectives = [o.strip() for o in (objectives_raw or "").split(",") if o.strip()]
    if not objectives:
        objectives = ["Complete the assigned task"]

    tasks_raw = questionary.text(
        "List tasks (comma-separated, or press Enter for a single task)"
    ).ask()
    tasks = [t.strip() for t in (tasks_raw or "").split(",") if t.strip()]
    if not tasks:
        tasks = [plan_title]

    dod_raw = questionary.text(
        "Definition of done (comma-separated)"
    ).ask()
    dod = [d.strip() for d in (dod_raw or "").split(",") if d.strip()]
    if not dod:
        dod = ["All tasks completed", "Tests pass"]

    estimated_time = questionary.text("Estimated time?", default="1–2 hours").ask() or "1–2 hours"

    risks_raw = questionary.text(
        "Known risks? (comma-separated, or Enter to skip)"
    ).ask()
    risks = [r.strip() for r in (risks_raw or "").split(",") if r.strip()]

    plan = PlanModel(
        title=plan_title,
        objectives=objectives,
        tasks=tasks,
        definition_of_done=dod,
        estimated_time=estimated_time,
        risks=risks,
    )

    plan_md = render_plan(plan)
    console.print("\n[bold]Your PLAN.md:[/]\n")
    console.print(plan_md)

    # ── Hard gate ────────────────────────────────────────────────────────
    console.rule("[bold red]HARD GATE[/]")
    console.print(
        "[yellow]Review the plan above. "
        "Type [bold]YES[/] to proceed or anything else to abort.[/]"
    )
    confirmation = input("Confirm: ").strip()
    if confirmation != "YES":
        console.print("[red]Aborted.[/] No worktree was created.")
        raise typer.Exit(0)

    if dry_run:
        console.print("[dim]--dry-run: stopping here. No worktree created.[/]")
        raise typer.Exit(0)

    # ── Phase 2: Create worktree + sensitive file stubs ──────────────────
    console.print("\n[bold cyan]Phase 2:[/] Creating worktree…")

    engine = WorktreeEngine(project_root)
    meta = engine.create_worktree(task_description=plan_title)

    console.print(f"  Worktree: [green]{meta.worktree_path}[/]")
    console.print(f"  Branch:   [green]{meta.branch_name}[/]")
    console.print(f"  Session:  [bold]{meta.session_id}[/]")

    # Write PLAN.md into worktree
    plan_file = Path(meta.worktree_path) / "PLAN.md"
    plan_file.write_text(plan_md, encoding="utf-8")
    console.print("  Wrote [green]PLAN.md[/] → worktree")

    # Write WORKSPACE.md into worktree
    shutil.copy2(workspace_path, Path(meta.worktree_path) / "WORKSPACE.md")

    # Sensitive file stubs
    sfh = SensitiveFileHandler(Path(meta.worktree_path))
    stubs = sfh.inject_stubs(info.project_type.value, source_root=project_root)
    if stubs:
        console.print(f"  Created {len(stubs)} sensitive-file stub(s)")

    # Inject Copilot instructions
    copilot_instructions = render_copilot_instructions(plan, ws_model, meta.session_id)
    instr_dir = Path(meta.worktree_path) / ".github"
    instr_dir.mkdir(parents=True, exist_ok=True)
    (instr_dir / "copilot-instructions.md").write_text(
        copilot_instructions, encoding="utf-8"
    )
    sec_dir = instr_dir / "instructions"
    sec_dir.mkdir(parents=True, exist_ok=True)
    (sec_dir / "security.instructions.md").write_text(
        render_security_instructions(info.project_type.value), encoding="utf-8"
    )
    console.print("  Wrote [green]Copilot instructions[/]")

    # Update project local config
    local_cfg = load_project_config(project_root)
    local_cfg.last_session_id = meta.session_id
    save_project_config(project_root, local_cfg)

    # ── Summary ──────────────────────────────────────────────────────────
    console.print()
    console.rule("[green]Session Ready[/]")
    console.print(f"\n[bold]Session ID:[/] {meta.session_id}")
    console.print(f"[bold]Worktree:[/]   {meta.worktree_path}")
    console.print(f"\nTo enter the worktree:\n  [bold]cd {meta.worktree_path}[/]\n")

    # Auto-launch IDE
    ide_choice_str = ide or "auto"
    from koteguard.models import IDEChoice as _IDEChoice
    try:
        ide_enum = _IDEChoice(ide_choice_str)
    except ValueError:
        ide_enum = _IDEChoice.AUTO

    launcher = IDELauncher(Path(meta.worktree_path))
    if launcher.launch_ide(ide_enum):
        console.print("[green]IDE launched.[/]")
    else:
        console.print(
            "[dim]No IDE detected – open the worktree manually.[/]"
        )


# ---------------------------------------------------------------------------
# ide – fast path
# ---------------------------------------------------------------------------


@app.command()
def ide(
    session: Annotated[
        Optional[str],
        typer.Argument(help="Session ID (default: most recent active session)"),
    ] = None,
    ide_override: Annotated[
        Optional[str],
        typer.Option("--ide", help="IDE override: android | ios"),
    ] = None,
) -> None:
    """Fast path: launch IDE for an existing agent worktree."""
    from koteguard.launcher import IDELauncher
    from koteguard.models import IDEChoice as _IDEChoice
    from koteguard.worktree import list_sessions, load_session

    meta = None
    if session:
        meta = load_session(session)
    else:
        sessions = list_sessions()
        active = [s for s in sessions if s.status == "active"]
        if active:
            meta = active[-1]

    if not meta:
        err_console.print("[red]No active session found.[/]")
        raise typer.Exit(1)

    worktree_path = Path(meta.worktree_path)
    if not worktree_path.exists():
        err_console.print(f"[red]Worktree not found:[/] {worktree_path}")
        raise typer.Exit(1)

    ide_str = ide_override or "auto"
    try:
        ide_enum = _IDEChoice(ide_str)
    except ValueError:
        ide_enum = _IDEChoice.AUTO

    launcher = IDELauncher(worktree_path)
    if launcher.launch_ide(ide_enum):
        console.print(f"[green]IDE launched[/] for session [bold]{meta.session_id}[/]")
    else:
        console.print(
            f"[yellow]No IDE detected.[/] Enter the worktree manually:\n"
            f"  cd {worktree_path}"
        )


# ---------------------------------------------------------------------------
# cli – fast path for terminal Copilot CLI
# ---------------------------------------------------------------------------


@app.command()
def cli(
    session: Annotated[
        Optional[str],
        typer.Argument(help="Session ID (default: most recent active session)"),
    ] = None,
) -> None:
    """Fast path: open a terminal at the agent worktree."""
    from koteguard.launcher import IDELauncher
    from koteguard.worktree import list_sessions, load_session

    meta = None
    if session:
        meta = load_session(session)
    else:
        sessions = list_sessions()
        active = [s for s in sessions if s.status == "active"]
        if active:
            meta = active[-1]

    if not meta:
        err_console.print("[red]No active session found.[/]")
        raise typer.Exit(1)

    worktree_path = Path(meta.worktree_path)
    launcher = IDELauncher(worktree_path)

    console.print(f"[bold]Session:[/]  {meta.session_id}")
    console.print(f"[bold]Worktree:[/] {worktree_path}")
    console.print(f"\n[dim]Run:[/]  {launcher.print_cd_command()}\n")
    launcher.open_terminal()


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command()
def status() -> None:
    """Show a Rich table of all agent worktrees."""
    from koteguard.worktree import list_sessions

    sessions = list_sessions()

    table = Table(title="KoteGuard Sessions", show_header=True, header_style="bold cyan")
    table.add_column("Session ID", style="bold")
    table.add_column("Project")
    table.add_column("Status")
    table.add_column("Worktree Path", overflow="fold")
    table.add_column("Created At")

    status_style = {
        "active": "green",
        "completed": "dim",
        "discarded": "red",
        "pending_review": "yellow",
    }

    for s in sessions:
        created = (
            s.created_at.strftime("%Y-%m-%d %H:%M")
            if isinstance(s.created_at, datetime)
            else str(s.created_at)
        )
        style = status_style.get(str(s.status), "")
        table.add_row(
            s.session_id,
            s.project_slug,
            f"[{style}]{s.status}[/]" if style else str(s.status),
            str(s.worktree_path),
            created,
        )

    if not sessions:
        console.print("[dim]No sessions found.[/]")
        return

    console.print(table)


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------


@app.command()
def cleanup(
    session: Annotated[
        Optional[str],
        typer.Argument(help="Session ID to clean up"),
    ] = None,
    accept: Annotated[
        bool,
        typer.Option("--accept", help="Merge changes back and remove worktree"),
    ] = False,
    discard: Annotated[
        bool,
        typer.Option("--discard", help="Discard all changes and remove worktree"),
    ] = False,
    all_sessions: Annotated[
        bool,
        typer.Option("--all", help="Apply to all sessions"),
    ] = False,
) -> None:
    """Cleanup agent worktrees: --accept or --discard."""
    from koteguard.worktree import WorktreeEngine, list_sessions, load_session

    if not accept and not discard:
        err_console.print("[red]Specify --accept or --discard[/]")
        raise typer.Exit(1)

    engine = WorktreeEngine()

    targets: list[str] = []
    if all_sessions:
        sessions = list_sessions()
        targets = [s.session_id for s in sessions if s.status == "active"]
    elif session:
        targets = [session]
    else:
        # Default: most recent active
        sessions = list_sessions()
        active = [s for s in sessions if s.status == "active"]
        if active:
            targets = [active[-1].session_id]

    if not targets:
        console.print("[dim]No active sessions to clean up.[/]")
        return

    for sid in targets:
        if accept:
            ok = engine.accept_worktree(sid)
            if ok:
                console.print(f"[green]Accepted[/] session {sid}")
            else:
                err_console.print(f"[red]Failed[/] to accept session {sid}")
        elif discard:
            ok = engine.discard_worktree(sid)
            if ok:
                console.print(f"[yellow]Discarded[/] session {sid}")
            else:
                err_console.print(f"[red]Failed[/] to discard session {sid}")


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


@app.command()
def validate(
    plan_file: Annotated[
        Optional[Path],
        typer.Argument(help="Path to PLAN.md (default: ./PLAN.md)"),
    ] = None,
    workspace_file: Annotated[
        Optional[Path],
        typer.Option("--workspace", "-w", help="Path to WORKSPACE.md"),
    ] = None,
) -> None:
    """Validate a PLAN.md (and optionally WORKSPACE.md) against the schema."""
    from koteguard.validation import validate_plan_file, validate_workspace_file

    plan_path = plan_file or Path.cwd() / "PLAN.md"

    result = validate_plan_file(plan_path)

    if result.errors:
        console.print(f"[bold red]PLAN.md validation FAILED:[/] {plan_path}")
        for err in result.errors:
            console.print(f"  [red]✗[/] {err}")
    else:
        console.print(f"[green]✓ PLAN.md is valid:[/] {plan_path}")

    for warn in result.warnings:
        console.print(f"  [yellow]⚠[/] {warn}")

    if workspace_file:
        ws_result = validate_workspace_file(workspace_file)
        if ws_result.errors:
            console.print(f"[bold red]WORKSPACE.md validation FAILED:[/] {workspace_file}")
            for err in ws_result.errors:
                console.print(f"  [red]✗[/] {err}")
        else:
            console.print(f"[green]✓ WORKSPACE.md is valid:[/] {workspace_file}")
        for warn in ws_result.warnings:
            console.print(f"  [yellow]⚠[/] {warn}")

    if not result:
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------


@app.command()
def version() -> None:
    """Print KoteGuard version."""
    console.print(f"KoteGuard v{__version__}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
