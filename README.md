# KoteGuard 🛡️

> Safe GitHub Copilot agent sandboxing for mobile developers (Android + iOS).

KoteGuard (`kote`) runs Copilot agents in isolated **git worktrees** so they can
never accidentally commit secrets, break your main branch, or touch real signing
credentials.

## Features

- 🔍 **Smart project analysis** – auto-detects Android, iOS, Flutter, React Native
- 📋 **Interactive planning wizard** – structured `PLAN.md` with hard approval gate
- 🌿 **Isolated git worktrees** – agents work on a dedicated branch, never `main`
- 🔒 **Sensitive file stubs** – `.jks`, `google-services.json`, `.p12`, etc. replaced with placeholders
- 📝 **Dual Copilot instructions** – task context + security rules injected automatically
- 📊 **Session tracking** – rich status table, JSONL audit trail
- ✅ **Validation** – validate `PLAN.md` and `WORKSPACE.md` against schema

## Installation

```bash
pip install koteguard
```

Or from source:

```bash
git clone https://github.com/your-org/KoteGuard.git
cd KoteGuard
pip install -e ".[dev]"
```

## Quick Start

```bash
# Full wizard: analyse project, plan, create worktree, launch IDE
kote prep

# Check status of all agent sessions
kote status

# Launch IDE for the most recent active session
kote ide

# Open a terminal at the worktree
kote cli

# Accept changes (merge back) or discard
kote cleanup --accept
kote cleanup --discard

# Validate a PLAN.md
kote validate PLAN.md
```

## Project Structure

```
src/koteguard/
├── cli.py              # Typer CLI application
├── models.py           # Pydantic v2 models
├── config.py           # TOML config management
├── project_scanner.py  # Phase 0: smart project analysis
├── worktree.py         # Git worktree engine
├── sensitive_files.py  # Sensitive file stub handler
├── planning.py         # PLAN.md / WORKSPACE.md / instructions
├── launcher.py         # IDE & terminal launcher
├── validation.py       # PLAN.md validation + audit
└── templates.py        # Template file management

templates/
├── WORKSPACE.md
├── PLAN.md
├── TASK.md
├── instructions.md
├── security.instructions.md
└── AGENTS.md
```

## Commands

| Command | Description |
|---------|-------------|
| `kote prep` | Full interactive wizard |
| `kote ide [session]` | Launch IDE for a session |
| `kote cli [session]` | Open terminal at worktree |
| `kote status` | Rich table of all sessions |
| `kote cleanup --accept` | Merge changes back + remove worktree |
| `kote cleanup --discard` | Discard changes + remove worktree |
| `kote validate [plan.md]` | Validate PLAN.md against schema |

## Security Model

- **No PLAN → No Agent** – the hard gate requires typing `YES` to proceed
- **Agents never in primary working tree** – always an isolated git worktree
- **Sensitive files never exposed** – stubs replace real credentials
- **Dual instructions** – Copilot gets task context AND security rules
- **JSONL audit trail** – every action logged to `~/.kote/audit.jsonl`

## License

MIT
