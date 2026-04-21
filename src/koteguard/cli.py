"""KoteGuard CLI – main Typer application."""

from __future__ import annotations

import shutil
import sys
from datetime import datetime, timezone
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

android_app = typer.Typer(
    name="android",
    help="Android CLI detection and skills commands",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
app.add_typer(android_app, name="android")

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
    android_first: Annotated[
        bool,
        typer.Option("--android-first", help="Enable Android skills wizard"),
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
    from koteguard.models import IDEChoice, PlanModel, ProjectType
    from koteguard.planning import (
        render_copilot_instructions,
        render_plan,
        render_security_instructions,
        workspace_from_project_info,
        render_workspace,
    )
    from koteguard.project_scanner import ProjectScanner
    from koteguard.sensitive_files import SensitiveFileHandler
    from koteguard.templates import get_template, write_template
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

    if info.android_cli_available:
        console.print("  Android CLI: [green]✓ available[/]")
    if info.detected_skills:
        console.print(f"  Detected skills: [dim]{', '.join(info.detected_skills)}[/]")

    ws_model = workspace_from_project_info(info)

    if not workspace_exists:
        kote_dir.mkdir(parents=True, exist_ok=True)
        workspace_path.write_text(render_workspace(ws_model), encoding="utf-8")
        console.print(f"  Created [green]{workspace_path.relative_to(project_root)}[/]")
    else:
        console.print(f"  Using existing [dim]{workspace_path.relative_to(project_root)}[/]")

    ensure_project_gitignore(project_root)

    # ── Android skills wizard (--android-first) ──────────────────────────
    selected_skills: list[str] = []
    if android_first and info.project_type in (ProjectType.ANDROID, ProjectType.MONOREPO):
        if not info.android_cli_available:
            console.print("[yellow]⚠ Android CLI not detected – some features may be unavailable[/]")

        console.print("\n[bold cyan]Android Skills:[/] Select skills to enable\n")
        from koteguard.templates import _templates_dir
        skills_dir = _templates_dir() / "android-skills"
        available_skills: list[str] = []
        if skills_dir.exists():
            available_skills = [
                p.stem.replace(".skill", "") for p in sorted(skills_dir.glob("*.skill.md"))
            ]
        if not available_skills:
            available_skills = ["navigation3", "edge-to-edge", "agp9", "compose-migration"]

        suggested = info.detected_skills
        choices = questionary.checkbox(
            "Which Android skills should the agent use?",
            choices=available_skills,
            default=suggested,
        ).ask()
        selected_skills = choices or []

    # ── Phase 1: Interactive planning ────────────────────────────────────
    console.print("\n[bold cyan]Phase 1:[/] Planning\n")

    while True:
        plan_title = questionary.text("What should the agent do? (brief title)").ask()
        if not plan_title:
            err_console.print("[red]Cancelled.[/]")
            raise typer.Exit(0)

        objectives_raw = questionary.text("List objectives (comma-separated)").ask()
        objectives = [o.strip() for o in (objectives_raw or "").split(",") if o.strip()]
        if not objectives:
            objectives = ["Complete the assigned task"]

        tasks_raw = questionary.text(
            "List tasks (comma-separated, or press Enter for a single task)"
        ).ask()
        tasks = [t.strip() for t in (tasks_raw or "").split(",") if t.strip()]
        if not tasks:
            tasks = [plan_title]

        dod_raw = questionary.text("Definition of done (comma-separated)").ask()
        dod = [d.strip() for d in (dod_raw or "").split(",") if d.strip()]
        if not dod:
            dod = ["All tasks completed", "Tests pass"]

        estimated_time = (
            questionary.text("Estimated time?", default="1–2 hours").ask() or "1–2 hours"
        )

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
            android_skills=selected_skills,
        )

        plan_md = render_plan(plan)
        console.print("\n[bold]Your PLAN.md:[/]\n")
        console.print(plan_md)

        # ── Hard gate ────────────────────────────────────────────────────
        console.rule("[bold red]HARD GATE[/]")
        console.print(
            "[yellow]Review the plan above. "
            "Type [bold]YES[/] to proceed, [bold]refine[/] to edit, "
            "or anything else to abort.[/]"
        )
        confirmation = input("Confirm: ").strip()
        if confirmation == "YES":
            break
        elif confirmation == "refine":
            console.print("[dim]Re-entering planning wizard with current values…[/]")
            continue
        else:
            console.print("[red]Aborted.[/] No worktree was created.")
            raise typer.Exit(0)

    if dry_run:
        console.print("[dim]--dry-run: stopping here. No worktree created.[/]")
        raise typer.Exit(0)

    # ── Phase 2: Create worktree + sensitive file stubs ──────────────────
    console.print("\n[bold cyan]Phase 2:[/] Creating worktree…")

    engine = WorktreeEngine(project_root)
    meta = engine.create_worktree(
        task_description=plan_title,
        plan_title=plan_title,
    )

    console.print(f"  Worktree: [green]{meta.worktree_path}[/]")
    console.print(f"  Branch:   [green]{meta.branch_name}[/]")
    console.print(f"  Session:  [bold]{meta.session_id}[/]")

    # Write PLAN.md into worktree
    plan_file = Path(meta.worktree_path) / "PLAN.md"
    plan_file.write_text(plan_md, encoding="utf-8")
    console.print("  Wrote [green]PLAN.md[/] → worktree")

    # Write TASK.md via templates.py
    task_constraints = "\n".join(f"- {c}" for c in ["Stay on the assigned branch", "No git push"])
    try:
        write_template(
            "TASK.md",
            Path(meta.worktree_path) / "TASK.md",
            description=plan_title,
            session_id=meta.session_id,
            context=f"Project: {ws_model.project_name}. Tech: {', '.join(ws_model.tech_stack[:3])}",
            constraints=task_constraints,
        )
        console.print("  Wrote [green]TASK.md[/] → worktree")
    except Exception:
        pass

    # Write AGENTS.md via templates.py
    try:
        agents_content = get_template("AGENTS.md")
        (Path(meta.worktree_path) / "AGENTS.md").write_text(agents_content, encoding="utf-8")
        console.print("  Wrote [green]AGENTS.md[/] → worktree")
    except Exception:
        pass

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
    (instr_dir / "copilot-instructions.md").write_text(copilot_instructions, encoding="utf-8")
    sec_dir = instr_dir / "instructions"
    sec_dir.mkdir(parents=True, exist_ok=True)
    (sec_dir / "security.instructions.md").write_text(
        render_security_instructions(info.project_type.value), encoding="utf-8"
    )
    console.print("  Wrote [green]Copilot instructions[/]")

    # Copy context files to sessions/{id}/context/
    engine.copy_context_files(
        meta.session_id,
        {
            "PLAN.md": plan_file,
            "TASK.md": Path(meta.worktree_path) / "TASK.md",
            "copilot-instructions.md": instr_dir / "copilot-instructions.md",
            "security.instructions.md": sec_dir / "security.instructions.md",
        },
    )

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
        console.print("[dim]No IDE detected – open the worktree manually.[/]")


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
    """Fast path: open a terminal at the agent worktree with full Copilot CLI command."""
    from koteguard.launcher import IDELauncher, build_copilot_cli_command
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
    copilot_cmd = build_copilot_cli_command(worktree_path)

    console.print(f"[bold]Session:[/]  {meta.session_id}")
    console.print(f"[bold]Worktree:[/] {worktree_path}")
    console.print(f"\n[bold]Run Copilot CLI:[/]")
    console.print(f"  [green]{copilot_cmd}[/]\n")
    launcher.open_terminal()


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command()
def status() -> None:
    """Show a Rich table of all agent worktrees."""
    from koteguard.worktree import list_sessions

    sessions = list_sessions()
    now = datetime.now(tz=timezone.utc)

    table = Table(title="KoteGuard Sessions", show_header=True, header_style="bold cyan")
    table.add_column("Session ID", style="bold")
    table.add_column("Project")
    table.add_column("Status")
    table.add_column("Session Age")
    table.add_column("Android CLI")
    table.add_column("Skills")
    table.add_column("Context Pressure")
    table.add_column("Created At")

    status_style = {
        "active": "green",
        "completed": "dim",
        "discarded": "red",
        "pending_review": "yellow",
    }

    old_sessions_found = False

    for s in sessions:
        created = (
            s.created_at.strftime("%Y-%m-%d %H:%M")
            if isinstance(s.created_at, datetime)
            else str(s.created_at)
        )
        style = status_style.get(str(s.status), "")

        # Session age
        if isinstance(s.created_at, datetime):
            age_seconds = (now - s.created_at.replace(tzinfo=timezone.utc) if s.created_at.tzinfo is None else (now - s.created_at)).total_seconds()
            if age_seconds < 3600:
                age_str = f"{int(age_seconds / 60)}m ago"
            elif age_seconds < 86400:
                age_str = f"{age_seconds / 3600:.1f}h ago"
            else:
                age_str = f"{age_seconds / 86400:.1f}d ago"
                if str(s.status) == "active":
                    old_sessions_found = True
        else:
            age_str = "unknown"

        # Android CLI
        android_cli_str = "[green]✓[/]" if s.android_cli_available else "[red]✗[/]"

        # Skills count
        skills_count = len(s.skills_loaded) if s.skills_loaded else 0
        skills_str = str(skills_count) if skills_count > 0 else "—"

        # Context pressure estimate
        worktree_path = Path(str(s.worktree_path))
        context_pressure = "Low"
        if worktree_path.exists():
            plan_path = worktree_path / "PLAN.md"
            if plan_path.exists():
                plan_size = plan_path.stat().st_size
                if plan_size > 10000:
                    context_pressure = "High"
                elif plan_size > 3000:
                    context_pressure = "Medium"
        pressure_color = {"Low": "green", "Medium": "yellow", "High": "red"}.get(context_pressure, "")
        pressure_str = f"[{pressure_color}]{context_pressure}[/]" if pressure_color else context_pressure

        table.add_row(
            s.session_id,
            s.project_slug,
            f"[{style}]{s.status}[/]" if style else str(s.status),
            age_str,
            android_cli_str,
            skills_str,
            pressure_str,
            created,
        )

    if not sessions:
        console.print("[dim]No sessions found.[/]")
        return

    console.print(table)

    if old_sessions_found:
        console.print(
            "\n[yellow]Tip:[/] Sessions older than 24h may benefit from a fresh worktree"
        )


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
    force: Annotated[
        bool,
        typer.Option("--force", help="Force acceptance even when validation has errors"),
    ] = False,
    compact: Annotated[
        bool,
        typer.Option("--compact", help="Prompt for session summary to append to WORKSPACE.md"),
    ] = False,
) -> None:
    """Cleanup agent worktrees: --accept or --discard."""
    import questionary

    from koteguard.config import SESSIONS_DIR
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
        sessions = list_sessions()
        active = [s for s in sessions if s.status == "active"]
        if active:
            targets = [active[-1].session_id]

    if not targets:
        console.print("[dim]No active sessions to clean up.[/]")
        return

    for sid in targets:
        if accept:
            meta = load_session(sid)
            if meta:
                worktree_path = Path(meta.worktree_path)

                # Auto-run validation
                from koteguard.validation import (
                    render_validation_report,
                    validate_plan_file,
                    validate_changes_against_plan,
                    write_validation_report,
                )

                plan_path = worktree_path / "PLAN.md"
                plan_result = validate_plan_file(plan_path)

                # Get changed files
                changed_files: list[str] = []
                try:
                    import git as _git
                    repo = _git.Repo(Path(meta.project_root), search_parent_directories=True)
                    diff_output = repo.git.diff(f"HEAD...{meta.branch_name}", "--name-only")
                    changed_files = [f for f in diff_output.splitlines() if f.strip()]
                except Exception:
                    pass

                changes_result = validate_changes_against_plan(
                    worktree_path, plan_path, changed_files
                )

                # Generate report
                report_content = render_validation_report(
                    session_id=sid,
                    plan_result=plan_result,
                    changes_result=changes_result,
                    skills_result=None,
                    worktree_path=worktree_path,
                    plan_path=plan_path,
                    created_at=meta.created_at,
                )
                write_validation_report(sid, report_content)

                # Display validation summary
                if plan_result.errors or changes_result.errors:
                    console.print(f"[bold red]Validation errors for session {sid}:[/]")
                    for e in plan_result.errors + changes_result.errors:
                        console.print(f"  [red]✗[/] {e}")
                    if not force:
                        console.print(
                            "[yellow]Use --force to accept anyway.[/]"
                        )
                        err_console.print(f"[red]Blocked[/] session {sid} due to validation errors")
                        continue
                else:
                    console.print(f"[green]✓ Validation passed[/] for session {sid}")

                for w in plan_result.warnings + changes_result.warnings:
                    console.print(f"  [yellow]⚠[/] {w}")

            ok = engine.accept_worktree(sid, force=force)
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

    # --compact: accumulate session summary to WORKSPACE.md
    if compact:
        import questionary as q
        summary = q.text(
            "Session summary (what was accomplished, key decisions, lessons learned):"
        ).ask()
        if summary:
            _append_workspace_summary(summary)


def _append_workspace_summary(summary: str) -> None:
    """Append a session summary section to ~/.kote/WORKSPACE.md."""
    workspace_path = Path.home() / ".kote" / "WORKSPACE.md"
    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    section = f"\n## Session Summary ({date_str})\n\n{summary}\n"

    if workspace_path.exists():
        existing = workspace_path.read_text(encoding="utf-8")
        workspace_path.write_text(existing + section, encoding="utf-8")
    else:
        workspace_path.write_text(
            f"# KoteGuard Knowledge Base\n{section}", encoding="utf-8"
        )
    console.print(f"[green]✓ Summary appended to[/] {workspace_path}")


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
# android – subcommand group
# ---------------------------------------------------------------------------


@android_app.command("skills")
def android_skills(
    project: Annotated[
        Optional[Path],
        typer.Option("--project", "-p", help="Project root (default: cwd)"),
    ] = None,
) -> None:
    """List available Android skills and suggest relevant ones for the current project."""
    from koteguard.templates import _templates_dir
    from koteguard.project_scanner import ProjectScanner

    table = Table(
        title="Android Skills", show_header=True, header_style="bold cyan"
    )
    table.add_column("Skill", style="bold")
    table.add_column("Description")
    table.add_column("Suggested")

    # Detect project suggestions
    project_root = project or Path.cwd()
    suggested: list[str] = []
    try:
        scanner = ProjectScanner(project_root)
        info = scanner.scan()
        suggested = info.detected_skills
    except Exception:
        pass

    # Read from templates
    skills_dir = _templates_dir() / "android-skills"
    skill_entries: list[tuple[str, str]] = []
    if skills_dir.exists():
        for skill_file in sorted(skills_dir.glob("*.skill.md")):
            skill_name = skill_file.stem.replace(".skill", "")
            description = ""
            try:
                content = skill_file.read_text(encoding="utf-8")
                # Extract description from first paragraph after H1
                lines = content.splitlines()
                for i, line in enumerate(lines):
                    if line.startswith("# ") and i + 2 < len(lines):
                        description = lines[i + 2].strip() if lines[i + 1].strip() == "" else lines[i + 1].strip()
                        break
            except Exception:
                pass
            skill_entries.append((skill_name, description or "Android best practices skill"))
    else:
        # Fallback list
        skill_entries = [
            ("navigation3", "Navigation 3 library best practices"),
            ("edge-to-edge", "Edge-to-edge display implementation"),
            ("agp9", "Android Gradle Plugin 9 migration guide"),
            ("compose-migration", "Jetpack Compose migration patterns"),
        ]

    for skill_name, description in skill_entries:
        is_suggested = "✓" if skill_name in suggested else ""
        suggested_style = "green" if is_suggested else ""
        table.add_row(
            skill_name,
            description,
            f"[{suggested_style}]{is_suggested}[/]" if is_suggested else "",
        )

    console.print(table)

    if suggested:
        console.print(f"\n[dim]Suggested for your project: {', '.join(suggested)}[/]")
    else:
        console.print("\n[dim]Run `kote prep --android-first` to enable skills for a session.[/]")


@android_app.command("docs")
def android_docs() -> None:
    """Show Android Knowledge Base status and documentation links."""
    from koteguard.project_scanner import ProjectScanner
    from koteguard.config import check_worktree_context

    table = Table(title="Android Documentation", show_header=True, header_style="bold cyan")
    table.add_column("Resource", style="bold")
    table.add_column("URL")
    table.add_column("Status")

    docs = [
        ("Android Developers", "https://developer.android.com", "online"),
        ("Jetpack Compose", "https://developer.android.com/jetpack/compose", "online"),
        ("Navigation 3", "https://developer.android.com/guide/navigation", "online"),
        ("AGP Migration", "https://developer.android.com/build/migrate-to-declarative", "online"),
        ("Edge-to-Edge", "https://developer.android.com/develop/ui/views/layout/edge-to-edge", "online"),
    ]

    for name, url, status in docs:
        status_str = "[green]✓ available[/]" if status == "online" else "[red]✗ unavailable[/]"
        table.add_row(name, url, status_str)

    console.print(table)

    in_worktree = check_worktree_context()
    if in_worktree:
        console.print("\n[green]✓ Running inside a KoteGuard worktree[/]")
    else:
        console.print("\n[dim]Not inside a KoteGuard worktree[/]")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point wrapper for pip-installed console script."""
    app()


if __name__ == "__main__":
    main()
