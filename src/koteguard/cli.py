"""KoteGuard CLI – main Typer application."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

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

ios_app = typer.Typer(
    name="ios",
    help="iOS skill guides and project commands",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
app.add_typer(ios_app, name="ios")

sessions_app = typer.Typer(
    name="sessions",
    help="Manage KoteGuard session metadata",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
app.add_typer(sessions_app, name="sessions")

console = Console()
err_console = Console(stderr=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_starter_message(info: ProjectInfo, plan: PlanModel) -> str:  # noqa: F821
    """Build a compact, context-aware, token-friendly starter prompt.

    Uses the scan result (``info``) and the approved plan to generate a
    single plain-text message the user can paste directly into the agent.
    """

    parts: list[str] = ["Read PLAN.md and TASK.md."]

    # Project context — only include fields that were actually detected
    ctx: list[str] = [f"Project: {info.project_name} ({info.project_type.value}"]
    if info.project_type.value == "android":
        if info.android_min_sdk:
            ctx.append(f"minSdk={info.android_min_sdk}")
        if info.android_target_sdk:
            ctx.append(f"targetSdk={info.android_target_sdk}")
        if info.android_compile_sdk:
            ctx.append(f"compileSdk={info.android_compile_sdk}")
    elif info.project_type.value == "ios":
        if info.ios_deployment_target:
            ctx.append(f"minOS={info.ios_deployment_target}")
    parts.append(", ".join(ctx) + ")")

    # Skills — only if selected
    if plan.android_skills:
        parts.append(f"Skill guides injected: {', '.join(plan.android_skills)}. Refer to them.")

    # Tasks with their spec IDs
    for t in plan.tasks:
        parts.append(f"Task [{t.id}]: {t.description}")

    # SDD instruction
    parts.append("After each task mark done: true in the PLAN.md YAML block.")

    # Definition of done
    if plan.definition_of_done:
        parts.append(f"Done when: {'; '.join(plan.definition_of_done)}.")

    return "\n".join(parts)


def _require_git_repo(path: Path = Path.cwd()) -> Path:
    """Exit with an error if path is not inside a git repo."""
    import git

    try:
        repo = git.Repo(path, search_parent_directories=True)
        return Path(repo.working_tree_dir)
    except git.InvalidGitRepositoryError:
        err_console.print("[bold red]Error:[/] Not inside a git repository. Run `git init` first.")
        raise typer.Exit(1) from None


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
        Path | None,
        typer.Option("--project", "-p", help="Project root (default: cwd)"),
    ] = None,
    reconfigure: Annotated[
        bool,
        typer.Option("--reconfigure", help="Re-run Phase 0 project analysis"),
    ] = False,
    ide: Annotated[
        str | None,
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
    agent_mode_flag: Annotated[
        str | None,
        typer.Option(
            "--agent-mode",
            help="Agent mode override: copilot-cli | copilot-plugin | none",
        ),
    ] = None,
) -> None:
    """Full interactive wizard: analyse → plan → worktree → launch."""
    import questionary

    from koteguard.config import (
        ensure_project_gitignore,
        load_project_config,
        project_kote_dir,
        resolve_agent_mode,
        resolve_android_cli_enabled,
        save_project_config,
    )
    from koteguard.launcher import IDELauncher, build_copilot_cli_command
    from koteguard.models import AgentMode, IDEChoice, PlanModel, PlanTask, ProjectType, TaskModel
    from koteguard.planning import (
        render_copilot_instructions,
        render_plan,
        render_security_instructions,
        render_task,
        render_workspace,
        workspace_from_project_info,
    )
    from koteguard.project_scanner import ProjectScanner
    from koteguard.sensitive_files import SensitiveFileHandler
    from koteguard.templates import get_template
    from koteguard.worktree import WorktreeEngine

    _print_banner()
    project_root = _require_git_repo(project or Path.cwd())
    kote_dir = project_kote_dir(project_root)

    # ── Resolve feature flags ────────────────────────────────────────────
    android_cli_enabled = resolve_android_cli_enabled(project_root)

    # ── Phase 0: Project analysis ────────────────────────────────────────
    console.print("\n[bold cyan]Phase 0:[/] Analysing project…")

    workspace_path = kote_dir / "WORKSPACE.md"
    workspace_exists = workspace_path.exists() and not reconfigure

    scanner = ProjectScanner(project_root, android_cli_enabled=android_cli_enabled)
    info = scanner.scan()

    console.print(
        f"  Detected: [bold]{info.project_type.value}[/] (confidence {info.confidence:.0%})"
    )
    console.print(f"  Project name: [bold]{info.project_name}[/]")

    if android_cli_enabled and info.android_cli_available:
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
            console.print(
                "[yellow]⚠ Android CLI not detected – some features may be unavailable[/]"
            )

        console.print("\n[bold cyan]Android Skills:[/] Select skills to enable\n")
        from koteguard.config import ANDROID_SKILLS_CACHE_DIR
        from koteguard.templates import _templates_dir

        # Prefer user-synced skills (kote android update) over bundled templates
        skills_dir = (
            ANDROID_SKILLS_CACHE_DIR
            if ANDROID_SKILLS_CACHE_DIR.exists()
            and any(ANDROID_SKILLS_CACHE_DIR.glob("*.skill.md"))
            else _templates_dir() / "android-skills"
        )
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

    # ── Agent mode selection ─────────────────────────────────────────────
    if agent_mode_flag:
        try:
            chosen_mode = AgentMode(agent_mode_flag)
        except ValueError:
            err_console.print(f"[red]Unknown agent mode:[/] {agent_mode_flag}")
            raise typer.Exit(1) from None
    else:
        default_mode = resolve_agent_mode(project_root)
        mode_answer = questionary.select(
            "How will the agent run?",
            choices=[
                questionary.Choice("Copilot CLI (terminal, deny-tool flags)", value="copilot-cli"),
                questionary.Choice("Copilot Plugin (IDE chat panel)", value="copilot-plugin"),
                questionary.Choice("None (inject instructions only)", value="none"),
            ],
            default=default_mode.value,
        ).ask()
        chosen_mode = AgentMode(mode_answer or "copilot-cli")

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
        task_strings = [t.strip() for t in (tasks_raw or "").split(",") if t.strip()]
        if not task_strings:
            task_strings = [plan_title]
        # Build PlanTask objects with auto-IDs — these are the spec items
        tasks = [
            PlanTask(id=f"t{i}", description=desc, done=False)
            for i, desc in enumerate(task_strings, 1)
        ]

        dod_raw = questionary.text("Definition of done (comma-separated)").ask()
        dod = [d.strip() for d in (dod_raw or "").split(",") if d.strip()]
        if not dod:
            dod = ["All tasks completed", "Tests pass"]

        estimated_time = (
            questionary.text("Estimated time?", default="1–2 hours").ask() or "1–2 hours"
        )

        risks_raw = questionary.text("Known risks? (comma-separated, or Enter to skip)").ask()
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
        agent_mode=chosen_mode,
    )

    console.print(f"  Worktree: [green]{meta.worktree_path}[/]")
    console.print(f"  Branch:   [green]{meta.branch_name}[/]")
    console.print(f"  Session:  [bold]{meta.session_id}[/]")

    # Write PLAN.md into worktree
    plan_file = Path(meta.worktree_path) / "PLAN.md"
    plan_file.write_text(plan_md, encoding="utf-8")
    console.print("  Wrote [green]PLAN.md[/] → worktree")

    # Write TASK.md via render_task() (YAML front-matter spec)
    try:
        task_model = TaskModel(
            session_id=meta.session_id,
            description=plan_title,
            context=f"Project: {ws_model.project_name}. Tech: {', '.join(ws_model.tech_stack[:3])}",
            constraints=["Stay on the assigned branch", "No git push"],
        )
        task_md_content = render_task(task_model)
        (Path(meta.worktree_path) / "TASK.md").write_text(task_md_content, encoding="utf-8")
        console.print("  Wrote [green]TASK.md[/] → worktree")
    except Exception as exc:
        console.print(f"  [yellow]⚠ Warning:[/] could not write TASK.md: {exc}")

    # Write AGENTS.md via templates.py
    try:
        agents_content = get_template("AGENTS.md")
        (Path(meta.worktree_path) / "AGENTS.md").write_text(agents_content, encoding="utf-8")
        console.print("  Wrote [green]AGENTS.md[/] → worktree")
    except Exception as exc:
        console.print(f"  [yellow]⚠ Warning:[/] could not write AGENTS.md: {exc}")

    # Write WORKSPACE.md into worktree
    shutil.copy2(workspace_path, Path(meta.worktree_path) / "WORKSPACE.md")

    # Sensitive file stubs
    sfh = SensitiveFileHandler(Path(meta.worktree_path))
    stubs = sfh.inject_stubs(info.project_type.value, source_root=project_root)
    if stubs:
        console.print(f"  Created {len(stubs)} sensitive-file stub(s)")

    # Inject Copilot instructions
    copilot_instructions = render_copilot_instructions(
        plan, ws_model, meta.session_id, android_cli_enabled=android_cli_enabled
    )
    instr_dir = Path(meta.worktree_path) / ".github"
    instr_dir.mkdir(parents=True, exist_ok=True)
    (instr_dir / "copilot-instructions.md").write_text(copilot_instructions, encoding="utf-8")
    sec_dir = instr_dir / "instructions"
    sec_dir.mkdir(parents=True, exist_ok=True)
    (sec_dir / "security.instructions.md").write_text(
        render_security_instructions(
            info.project_type.value, android_cli_enabled=android_cli_enabled
        ),
        encoding="utf-8",
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
    console.print(f"\n[bold]Session ID:[/]  {meta.session_id}")
    console.print(f"[bold]Worktree:[/]    {meta.worktree_path}")
    console.print(f"[bold]Agent Mode:[/]  {chosen_mode.value}\n")

    # Mode-appropriate next step
    if chosen_mode == AgentMode.COPILOT_CLI:
        copilot_cmd = build_copilot_cli_command(Path(meta.worktree_path), agent_mode=chosen_mode)
        console.print("[bold]Run Copilot CLI:[/]")
        console.print(f"  [green]{copilot_cmd}[/]\n")
    elif chosen_mode == AgentMode.COPILOT_PLUGIN:
        console.print(
            f"[bold]Next step:[/] Open your IDE at the worktree path and use the Copilot chat panel:\n"
            f"  [dim]{meta.worktree_path}[/]\n"
        )
    else:  # none
        console.print(f"[bold]Next step:[/]\n  [bold]cd {meta.worktree_path}[/]\n")

    # ── Starter message ───────────────────────────────────────────────────
    console.rule("[dim]Starter Message[/]")
    console.print(_build_starter_message(info, plan))
    console.rule()

    # Auto-launch IDE
    ide_choice_str = ide or "auto"
    try:
        ide_enum = IDEChoice(ide_choice_str)
    except ValueError:
        ide_enum = IDEChoice.AUTO

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
        str | None,
        typer.Argument(help="Session ID (default: most recent active session)"),
    ] = None,
    ide_override: Annotated[
        str | None,
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
        raise typer.Exit(1) from None

    worktree_path = Path(meta.worktree_path)
    if not worktree_path.exists():
        err_console.print(f"[red]Worktree not found:[/] {worktree_path}")
        raise typer.Exit(1) from None

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
            f"[yellow]No IDE detected.[/] Enter the worktree manually:\n  cd {worktree_path}"
        )


# ---------------------------------------------------------------------------
# cli – fast path for terminal Copilot CLI
# ---------------------------------------------------------------------------


@app.command()
def cli(
    session: Annotated[
        str | None,
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
        raise typer.Exit(1) from None

    from koteguard.models import AgentMode as _AgentMode

    worktree_path = Path(meta.worktree_path)
    launcher = IDELauncher(worktree_path)
    mode = _AgentMode(meta.agent_mode) if meta.agent_mode else _AgentMode.COPILOT_CLI

    console.print(f"[bold]Session:[/]    {meta.session_id}")
    console.print(f"[bold]Worktree:[/]   {worktree_path}")
    console.print(f"[bold]Agent Mode:[/] {mode.value}\n")

    copilot_cmd = build_copilot_cli_command(worktree_path, agent_mode=mode)

    if copilot_cmd is not None:
        console.print("[bold]Run Copilot CLI:[/]")
        console.print(f"  [green]{copilot_cmd}[/]\n")
        launcher.open_terminal()
    elif mode == _AgentMode.COPILOT_PLUGIN:
        console.print(
            "[bold]Next step:[/] Open your IDE at the worktree path and use the Copilot chat panel."
        )
    else:
        console.print(f"[bold]Next step:[/]\n  cd {worktree_path}")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command()
def status() -> None:
    """Show a Rich table of all agent worktrees."""
    from koteguard.worktree import list_sessions

    sessions = list_sessions()
    now = datetime.now(tz=UTC)

    table = Table(title="KoteGuard Sessions", show_header=True, header_style="bold cyan")
    table.add_column("Session ID", style="bold")
    table.add_column("Plan")
    table.add_column("Project")
    table.add_column("Status")
    table.add_column("Session Age")
    table.add_column("Agent Mode")
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
            age_seconds = (
                now - s.created_at.replace(tzinfo=UTC)
                if s.created_at.tzinfo is None
                else (now - s.created_at)
            ).total_seconds()
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

        # Agent mode
        agent_mode_str = (
            str(s.agent_mode) if hasattr(s, "agent_mode") and s.agent_mode else "copilot-cli"
        )

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
        pressure_color = {"Low": "green", "Medium": "yellow", "High": "red"}.get(
            context_pressure, ""
        )
        pressure_str = (
            f"[{pressure_color}]{context_pressure}[/]" if pressure_color else context_pressure
        )

        plan_title_str = (s.plan_title[:35] + "…") if len(s.plan_title) > 35 else s.plan_title

        table.add_row(
            s.session_id,
            plan_title_str or "[dim]—[/]",
            s.project_slug,
            f"[{style}]{s.status}[/]" if style else str(s.status),
            age_str,
            agent_mode_str,
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
        console.print("\n[yellow]Tip:[/] Sessions older than 24h may benefit from a fresh worktree")


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------


@app.command()
def cleanup(
    session: Annotated[
        str | None,
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

    from koteguard.worktree import WorktreeEngine, list_sessions, load_session

    if not accept and not discard:
        err_console.print("[red]Specify --accept or --discard[/]")
        raise typer.Exit(1) from None

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
                    validate_changes_against_plan,
                    validate_plan_file,
                    write_validation_report,
                )

                # Check for uncommitted changes — they would be silently lost on merge
                try:
                    import git as _git

                    wt_repo = _git.Repo(worktree_path)
                    if wt_repo.is_dirty(untracked_files=False):
                        console.print(
                            f"[bold red]✗ Uncommitted changes detected in worktree[/] for session {sid}\n"
                            "  The agent modified files without committing — they will be permanently\n"
                            "  lost if cleanup proceeds.\n\n"
                            "  To preserve them, commit first:\n"
                            f"    cd {worktree_path}\n"
                            f"    git add -A && git commit -m 'agent: apply changes'\n"
                            f"    cd {meta.project_root}\n"
                            "    kote cleanup --accept\n\n"
                            "  Or to discard the changes and close the session:\n"
                            f"    kote cleanup {sid} --discard"
                        )
                        if not force:
                            err_console.print(
                                f"[red]Blocked[/] session {sid} — commit worktree changes first, "
                                "or use --force to proceed (uncommitted changes will be discarded)"
                            )
                            continue
                        else:
                            console.print(
                                "[yellow]--force: proceeding despite uncommitted changes "
                                "(they will not be merged)[/]"
                            )
                except Exception:
                    pass

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
                        console.print("[yellow]Use --force to accept anyway.[/]")
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

    # --compact: accumulate session summary to project-local WORKSPACE.md
    if compact:
        import questionary as q

        # Resolve project root from the most recently processed session
        _compact_project_root: Path | None = None
        for sid in targets:
            _m = load_session(sid)
            if _m:
                _compact_project_root = Path(_m.project_root)
                break

        summary = q.text(
            "Session summary (what was accomplished, key decisions, lessons learned):"
        ).ask()
        if summary:
            _append_workspace_summary(summary, project_root=_compact_project_root)


def _append_workspace_summary(summary: str, project_root: Path | None = None) -> None:
    """Append a session summary section to the project-local .kote/WORKSPACE.md.

    Falls back to ~/.kote/WORKSPACE.md when no project root is known.
    Writing to the project-local file ensures future worktrees pick up the
    accumulated knowledge (it is copied into each worktree during kote prep).
    """
    if project_root is not None:
        workspace_path = project_root / ".kote" / "WORKSPACE.md"
    else:
        workspace_path = Path.home() / ".kote" / "WORKSPACE.md"

    date_str = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
    section = f"\n## Session Summary ({date_str})\n\n{summary}\n"

    if workspace_path.exists():
        existing = workspace_path.read_text(encoding="utf-8")
        workspace_path.write_text(existing + section, encoding="utf-8")
    else:
        workspace_path.parent.mkdir(parents=True, exist_ok=True)
        workspace_path.write_text(f"# KoteGuard Knowledge Base\n{section}", encoding="utf-8")
    console.print(f"[green]✓ Summary appended to[/] {workspace_path}")


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


@app.command()
def validate(
    plan_file: Annotated[
        Path | None,
        typer.Argument(help="Path to PLAN.md (default: ./PLAN.md)"),
    ] = None,
    workspace_file: Annotated[
        Path | None,
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

    ws_result = None
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

    if not result or (ws_result is not None and not ws_result):
        raise typer.Exit(1) from None


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
        Path | None,
        typer.Option("--project", "-p", help="Project root (default: cwd)"),
    ] = None,
) -> None:
    """List available Android skills and suggest relevant ones for the current project.

    Cached skills from `kote android update` take priority over bundled skills.
    """
    from koteguard.config import ANDROID_SKILLS_CACHE_DIR
    from koteguard.project_scanner import ProjectScanner
    from koteguard.templates import _templates_dir

    table = Table(title="Android Skills", show_header=True, header_style="bold cyan")
    table.add_column("Skill", style="bold")
    table.add_column("Description")
    table.add_column("Source")
    table.add_column("Suggested")

    # Detect project suggestions
    project_root = project or Path.cwd()
    suggested: list[str] = []
    try:
        from koteguard.config import resolve_android_cli_enabled as _resolve_cli

        _android_cli_enabled = _resolve_cli(project_root)
        scanner = ProjectScanner(project_root, android_cli_enabled=_android_cli_enabled)
        info = scanner.scan()
        suggested = info.detected_skills
    except Exception:
        pass

    def _extract_description(skill_file: Path) -> str:
        try:
            content = skill_file.read_text(encoding="utf-8")
            lines = content.splitlines()
            for i, line in enumerate(lines):
                if line.startswith("# ") and i + 2 < len(lines):
                    return (
                        lines[i + 2].strip() if lines[i + 1].strip() == "" else lines[i + 1].strip()
                    )
        except Exception:
            pass
        return "Android best practices skill"

    # Merge: cached skills (from kote android update) override bundled skills
    skill_entries: dict[str, tuple[str, str]] = {}  # name → (description, source_label)

    bundled_dir = _templates_dir() / "android-skills"
    if bundled_dir.exists():
        for f in sorted(bundled_dir.glob("*.skill.md")):
            name = f.stem.replace(".skill", "")
            skill_entries[name] = (_extract_description(f), "bundled")

    if ANDROID_SKILLS_CACHE_DIR.exists():
        for f in sorted(ANDROID_SKILLS_CACHE_DIR.glob("*.skill.md")):
            name = f.stem.replace(".skill", "")
            skill_entries[name] = (_extract_description(f), "github.com/android/skills")

    if not skill_entries:
        skill_entries = {
            "navigation3": ("Navigation 3 library best practices", "bundled"),
            "edge-to-edge": ("Edge-to-edge display implementation", "bundled"),
            "agp9": ("Android Gradle Plugin 9 migration guide", "bundled"),
            "compose-migration": ("Jetpack Compose migration patterns", "bundled"),
        }

    for skill_name, (description, source) in sorted(skill_entries.items()):
        is_suggested = "✓" if skill_name in suggested else ""
        suggested_style = "green" if is_suggested else ""
        source_style = "cyan" if source != "bundled" else "dim"
        table.add_row(
            skill_name,
            description,
            f"[{source_style}]{source}[/]",
            f"[{suggested_style}]{is_suggested}[/]" if is_suggested else "",
        )

    console.print(table)

    if ANDROID_SKILLS_CACHE_DIR.exists():
        count = len(list(ANDROID_SKILLS_CACHE_DIR.glob("*.skill.md")))
        console.print(
            f"\n[cyan]{count} skill(s) synced from github.com/android/skills[/] "
            f"(run [bold]kote android update[/] to refresh)"
        )
    else:
        console.print(
            "\n[dim]Tip: run [bold]kote android update[/] to sync the latest official "
            "Android skill guides from github.com/android/skills[/]"
        )

    if suggested:
        console.print(f"[dim]Suggested for your project: {', '.join(suggested)}[/]")
    else:
        console.print("[dim]Run `kote prep --android-first` to enable skills for a session.[/]")


@android_app.command("update")
def android_update(
    force: Annotated[
        bool,
        typer.Option("--force", help="Re-download even if skill is already up to date"),
    ] = False,
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            help="GitHub personal access token (avoids rate limits). Also read from $GITHUB_TOKEN.",
            envvar="GITHUB_TOKEN",
        ),
    ] = None,
) -> None:
    """Sync Android skill guides from github.com/android/skills into ~/.kote/android-skills/.

    Skills are saved as flat <leaf-dir>.skill.md files under ANDROID_SKILLS_CACHE_DIR.
    KoteGuard will prefer cached skills over bundled ones during kote prep.
    """
    import json
    import urllib.request

    from koteguard.config import ANDROID_SKILLS_CACHE_DIR

    REPO_OWNER = "android"
    REPO_NAME = "skills"
    API_BASE = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents"

    def _api_get(path: str) -> list[dict]:
        url = f"{API_BASE}/{path}".rstrip("/")
        headers: dict[str, str] = {"User-Agent": "KoteGuard/kote-android-update"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())

    def _find_skills(path: str = "", depth: int = 0) -> list[tuple[str, str]]:
        """Recursively find (leaf_dir_name, download_url) for all SKILL.md files."""
        if depth > 5:
            return []
        try:
            items = _api_get(path)
        except Exception as exc:
            console.print(f"  [yellow]⚠ API error at {path or '/'}:[/] {exc}")
            return []
        found = []
        for item in items:
            if item["name"].startswith("."):
                continue
            if item["type"] == "file" and item["name"] == "SKILL.md":
                leaf = path.split("/")[-1] if path else "unknown"
                found.append((leaf, item["download_url"]))
            elif item["type"] == "dir":
                found.extend(_find_skills(item["path"], depth + 1))
        return found

    console.print(
        f"[bold cyan]Syncing Android skills[/] from "
        f"[link=https://github.com/{REPO_OWNER}/{REPO_NAME}]"
        f"github.com/{REPO_OWNER}/{REPO_NAME}[/link] …\n"
    )

    try:
        skill_refs = _find_skills()
    except Exception as exc:
        err_console.print(f"[red]Failed to reach GitHub API:[/] {exc}")
        raise typer.Exit(1) from None

    if not skill_refs:
        console.print("[yellow]No skills found in repo. Check your connection.[/]")
        raise typer.Exit(1) from None

    ANDROID_SKILLS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    added = updated = unchanged = 0
    for leaf_name, download_url in sorted(skill_refs):
        dest = ANDROID_SKILLS_CACHE_DIR / f"{leaf_name}.skill.md"
        try:
            req = urllib.request.Request(
                download_url,
                headers={"User-Agent": "KoteGuard/kote-android-update"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                new_content = resp.read().decode("utf-8")
        except Exception as exc:
            console.print(f"  [yellow]⚠ Could not download {leaf_name}:[/] {exc}")
            continue

        if dest.exists() and not force:
            existing = dest.read_text(encoding="utf-8")
            if existing == new_content:
                console.print(f"  [dim]—  {leaf_name}[/] (unchanged)")
                unchanged += 1
                continue
            dest.write_text(new_content, encoding="utf-8")
            console.print(f"  [cyan]↑  {leaf_name}[/] (updated)")
            updated += 1
        else:
            dest.write_text(new_content, encoding="utf-8")
            console.print(
                f"  [green]✓  {leaf_name}[/] {'(re-downloaded)' if force and dest.exists() else '(new)'}"
            )
            added += 1

    console.print(
        f"\n[green]Done.[/] {added} new, {updated} updated, {unchanged} unchanged.\n"
        f"Skills cached at: [dim]{ANDROID_SKILLS_CACHE_DIR}[/]\n"
        f"Run [bold]kote android skills[/] to see the full list."
    )


@android_app.command("docs")
def android_docs() -> None:
    """Show Android Knowledge Base status and documentation links."""
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
        (
            "Edge-to-Edge",
            "https://developer.android.com/develop/ui/views/layout/edge-to-edge",
            "online",
        ),
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
# init – interactive global config setup
# ---------------------------------------------------------------------------


@app.command()
def init() -> None:
    """Interactively configure KoteGuard global settings (~/.kote/config.toml)."""
    import questionary

    from koteguard.config import load_global_config, save_global_config
    from koteguard.models import AgentMode, IDEChoice

    _print_banner()
    cfg = load_global_config()

    console.print("[bold cyan]KoteGuard Init[/] – configure your global defaults\n")
    console.print("[dim]Press Enter to keep the current value shown in brackets.[/]\n")

    # Agent mode
    mode_answer = questionary.select(
        "Default agent mode?",
        choices=[
            questionary.Choice("Copilot CLI (terminal, deny-tool flags)", value="copilot-cli"),
            questionary.Choice("Copilot Plugin (IDE chat panel)", value="copilot-plugin"),
            questionary.Choice("None (inject instructions only)", value="none"),
        ],
        default=str(cfg.agent_mode),
    ).ask()
    if mode_answer:
        cfg.agent_mode = AgentMode(mode_answer)

    # Default IDE
    ide_answer = questionary.select(
        "Default IDE?",
        choices=[
            questionary.Choice("Auto-detect", value="auto"),
            questionary.Choice("Android Studio", value="android"),
            questionary.Choice("Xcode", value="ios"),
        ],
        default=str(cfg.default_ide),
    ).ask()
    if ide_answer:
        cfg.default_ide = IDEChoice(ide_answer)

    # Android CLI
    cfg.android_cli_enabled = (
        questionary.confirm(
            "Enable Android CLI integration?",
            default=cfg.android_cli_enabled,
        ).ask()
        or cfg.android_cli_enabled
    )

    # Worktrees dir
    wt_dir_answer = questionary.text(
        "Worktrees directory?",
        default=str(cfg.worktrees_dir),
    ).ask()
    if wt_dir_answer and wt_dir_answer.strip():
        cfg.worktrees_dir = Path(wt_dir_answer.strip())

    save_global_config(cfg)
    console.print(f"\n[green]✓ Config saved[/] → {Path.home() / '.kote' / 'config.toml'}")
    console.print(f"  agent_mode      = [bold]{cfg.agent_mode}[/]")
    console.print(f"  default_ide     = [bold]{cfg.default_ide}[/]")
    console.print(f"  android_cli     = [bold]{cfg.android_cli_enabled}[/]")
    console.print(f"  worktrees_dir   = [bold]{cfg.worktrees_dir}[/]")


# ---------------------------------------------------------------------------
# sessions prune – remove old session metadata
# ---------------------------------------------------------------------------


@sessions_app.command("prune")
def sessions_prune(
    days: Annotated[
        int,
        typer.Option("--days", help="Remove sessions older than N days (default: 30)"),
    ] = 30,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview what would be removed without deleting"),
    ] = False,
) -> None:
    """Remove completed/discarded session metadata older than N days."""
    import shutil as _shutil

    from koteguard.config import SESSIONS_DIR as _SD
    from koteguard.worktree import list_sessions

    now = datetime.now(tz=UTC)
    cutoff_seconds = days * 86400

    sessions = list_sessions()
    candidates = [
        s
        for s in sessions
        if str(s.status) in ("completed", "discarded")
        and (
            now - s.created_at.replace(tzinfo=UTC)
            if s.created_at.tzinfo is None
            else now - s.created_at
        ).total_seconds()
        > cutoff_seconds
    ]

    if not candidates:
        console.print(f"[dim]No completed/discarded sessions older than {days} days.[/]")
        return

    for s in candidates:
        session_dir = _SD / s.session_id
        if dry_run:
            console.print(
                f"  [dim]would remove[/] {s.session_id} "
                f"({s.plan_title[:40] or s.project_slug}, {s.status})"
            )
        else:
            try:
                _shutil.rmtree(session_dir, ignore_errors=True)
                console.print(f"  [yellow]removed[/] {s.session_id}")
            except Exception as exc:
                err_console.print(f"  [red]Failed to remove {s.session_id}:[/] {exc}")

    action = "Would remove" if dry_run else "Removed"
    console.print(f"\n[green]✓ {action} {len(candidates)} session(s)[/]")


# ---------------------------------------------------------------------------
# ios skills
# ---------------------------------------------------------------------------


@ios_app.command("skills")
def ios_skills(
    project: Annotated[
        Path | None,
        typer.Option("--project", "-p", help="Project root (default: cwd)"),
    ] = None,
) -> None:
    """List available iOS skill guides and suggest relevant ones for the current project."""
    from koteguard.templates import _templates_dir

    table = Table(title="iOS Skills", show_header=True, header_style="bold cyan")
    table.add_column("Skill", style="bold")
    table.add_column("Description")
    table.add_column("Suggested")

    # Detect project suggestions
    project_root = project or Path.cwd()
    suggested: list[str] = []
    try:
        from koteguard.config import resolve_android_cli_enabled as _resolve_cli
        from koteguard.project_scanner import ProjectScanner

        _android_cli_enabled = _resolve_cli(project_root)
        scanner = ProjectScanner(project_root, android_cli_enabled=_android_cli_enabled)
        info = scanner.scan()
        suggested = info.ios_detected_skills
    except Exception:
        pass

    # Read from templates/ios-skills/
    skills_dir = _templates_dir() / "ios-skills"
    skill_entries: list[tuple[str, str]] = []
    if skills_dir.exists():
        for skill_file in sorted(skills_dir.glob("*.skill.md")):
            skill_name = skill_file.stem.replace(".skill", "")
            description = ""
            try:
                content = skill_file.read_text(encoding="utf-8")
                lines = content.splitlines()
                for i, line in enumerate(lines):
                    if line.startswith("# ") and i + 2 < len(lines):
                        description = (
                            lines[i + 2].strip()
                            if lines[i + 1].strip() == ""
                            else lines[i + 1].strip()
                        )
                        break
            except Exception:
                pass
            skill_entries.append((skill_name, description or "iOS best practices skill"))
    else:
        skill_entries = [
            ("swiftui-patterns", "SwiftUI state management and scene lifecycle"),
            ("swift-concurrency", "async/await, actors, structured concurrency"),
            ("xctest", "XCTest, async testing, snapshot testing"),
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
        console.print("\n[dim]Run `kote prep` in your iOS project directory to enable skills.[/]")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point wrapper for pip-installed console script."""
    app()


if __name__ == "__main__":
    main()
