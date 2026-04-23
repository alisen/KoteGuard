<p align="center">
  <img src="koteguard.png" alt="KoteGuard" width="600">
</p>

<p align="center">
  <a href="https://koteguard.com"><img src="https://img.shields.io/badge/website-koteguard.com-blue?style=flat-square" alt="koteguard.com"></a>
  <img src="https://img.shields.io/badge/python-3.12%2B-blue?style=flat-square" alt="Python 3.12+">
  <a href="https://pypi.org/project/koteguard/"><img src="https://img.shields.io/pypi/v/koteguard?style=flat-square&label=version&color=orange&include_prereleases=true" alt="PyPI Version"></a>
  <img src="https://img.shields.io/badge/platform-Android%20%7C%20iOS-green?style=flat-square" alt="Platform">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey?style=flat-square" alt="MIT License">
  <a href="https://github.com/alisen/KoteGuard/actions/workflows/ci.yml"><img src="https://github.com/alisen/KoteGuard/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
</p>

<p align="center">
  Safe GitHub Copilot agent sandboxing for <strong>Android (Kotlin)</strong> and <strong>iOS (Swift)</strong> developers.
</p>

<p align="center">
  <code>kote prep</code> → isolated git worktree → agent works safely → <code>kote cleanup --accept</code>
</p>

---

KoteGuard runs Copilot agents in isolated **git worktrees** so they can never accidentally commit secrets, break your main branch, or touch real signing credentials. Every session is planned, gated, validated, and audited.

## Why KoteGuard?

| Problem | Without KoteGuard | With KoteGuard |
|---------|-------------------|----------------|
| Agent pushes to `main` | 💥 Happens | `--deny-tool='shell(git push)'` blocks it |
| Agent reads your `.jks` / `.p12` | 💥 Full access | Replaced with stubs before session starts |
| No record of what the agent did | 😬 Nothing | Per-session `audit.jsonl` + `validation-report.md` |
| Agent goes off-script | 😬 No way to know | PLAN.md hard gate + change validation on cleanup |
| Context bloat across sessions | 😬 Expensive | `--compact` accumulates knowledge into WORKSPACE.md |

---

## Features

- 🔍 **Smart project analysis** — auto-detects Android/iOS, parses `build.gradle` + `Info.plist`, scans docs
- 📋 **Interactive planning wizard** — builds `PLAN.md` with a refine loop and a hard `YES` gate
- 🌿 **Isolated git worktrees** — agent works on a dedicated branch, never touches `main`
- 🔒 **Sensitive file stubs** — `.jks`, `google-services.json`, `.p12`, `.env` replaced with safe placeholders
- 🤖 **Copilot CLI ready** — generates the complete `copilot --deny-tool=...` command for you
- 📊 **Session tracking** — rich status table with plan title, age, Android CLI status, skills loaded, context pressure
- ✅ **Auto-validation** — validates PLAN.md + changed files on `kote cleanup --accept`
- 🧰 **Android Skills** — official guides synced nightly from `github.com/android/skills`; `kote android update` fetches the latest
- 🍎 **iOS Skills** — bundled SwiftUI, Swift Concurrency, and XCTest guides; auto-detected from your Swift source
- 🔧 **Global config** — `kote init` wizard sets agent mode, IDE, and worktrees directory
- 🗂️ **Session hygiene** — `kote sessions prune` removes stale session metadata on your schedule
- 🧠 **Token hygiene** — `--compact` saves session knowledge back into `WORKSPACE.md`

---

## Installation

```bash
pip install koteguard
```

**Requires Python 3.12+**

Or install from source:

```bash
git clone https://github.com/alisen/KoteGuard.git
cd KoteGuard
pip install -e ".[dev]"
```

**Local install (no GitHub push needed — for testing before publishing):**

```bash
# Using pipx (recommended for CLI tools)
brew install pipx && pipx ensurepath
pipx install /path/to/KoteGuard

# Or with pip directly
pip install /path/to/KoteGuard
```

---

## Quick Start

```bash
# One-time setup (optional — configure your defaults)
kote init

cd your-android-or-ios-project

# 1. Run the wizard — it detects your project, plans, creates the worktree
kote prep

# 2. See what it created
kote status

# 3. Copy the ready-to-run Copilot CLI command
kote cli

# 4. Inside the worktree, make sure the agent committed its changes
#    KoteGuard diffs branch commits — uncommitted changes will not be merged
#    cd /path/to/worktree && git add -A && git commit -m "agent: apply changes"

# 5. Back in your project root — validate + merge back
cd your-android-or-ios-project   # same dir as step 1
kote cleanup --accept

# 6. Or throw it away
kote cleanup --discard
```

### Android-first (with skills wizard)

```bash
kote prep --android-first
# → detects Compose/Navigation/AGP usage
# → shows checkbox to select which skill guides to inject
# → pre-populates PLAN.md with selected skills
```

---

## How It Works

```
kote prep
  │
  ├── Phase 0: Scan project
  │     detect Android/iOS · parse build.gradle/Info.plist
  │     scan docs · detect Android CLI · suggest skills
  │
  ├── Phase 1: Interactive planning
  │     title · objectives · tasks · definition of done · risks
  │     ──── HARD GATE: type YES to proceed, refine to re-edit ────
  │
  └── Phase 2: Create worktree
        new git branch (kote/<session-id>-<slug>)
        writes: PLAN.md · TASK.md · AGENTS.md · WORKSPACE.md
                .github/copilot-instructions.md
                .github/instructions/security.instructions.md
        stubs:  google-services.json · *.jks · *.p12 · etc.
        logs:   sessions/<id>/context/ · logs/ · output/

kote cli
  └── prints: cd /worktree && COPILOT_CUSTOM_INSTRUCTIONS_DIRS=... copilot --deny-tool=...

[agent works here]

kote cleanup --accept
  ├── auto-validates PLAN.md + changed files
  ├── generates sessions/<id>/output/validation-report.md
  ├── merges branch back
  └── archives PLAN · TASK · diff · audit · report → .kote/history/
```

---

## Command Reference

| Command | Description |
|---------|-------------|
| `kote prep` | Full wizard: analyse → plan → worktree → IDE |
| `kote prep --android-first` | Wizard with Android skills selection |
| `kote prep --agent-mode <mode>` | Override agent mode: `copilot-cli` \| `copilot-plugin` \| `none` |
| `kote prep --dry-run` | Simulate without creating a worktree |
| `kote ide [session]` | Launch Android Studio or Xcode for a session |
| `kote cli [session]` | Print complete `copilot` command + open terminal |
| `kote status` | Rich table: all sessions with age, skills, context pressure |
| `kote cleanup --accept` | **Run from the original project root.** Validate → merge → archive history. Auto-picks most recent active session. |
| `kote cleanup <session-id> --accept` | Target a specific session by ID (find IDs with `kote status`) |
| `kote cleanup --discard` | Throw away changes, preserve audit trail |
| `kote cleanup --accept --force` | Accept even when validation has errors or uncommitted changes are detected |
| `kote cleanup --accept --compact` | Accept + save session summary to WORKSPACE.md |
| `kote validate [plan.md]` | Validate PLAN.md against schema |
| `kote validate -w WORKSPACE.md` | Also validate WORKSPACE.md |
| `kote android skills` | List all skills (cached + bundled) + suggest for current project |
| `kote android update` | Sync latest skill guides from `github.com/android/skills` |
| `kote android update --token <PAT>` | Same, with a GitHub token to avoid rate limits |
| `kote android docs` | Android KB links + worktree status |
| `kote ios skills` | List bundled iOS skill guides + suggest for current project |
| `kote sessions prune` | Remove completed/discarded session metadata older than 30 days |
| `kote sessions prune --days N` | Prune sessions older than N days |
| `kote sessions prune --dry-run` | Preview which sessions would be pruned |
| `kote init` | Interactively configure global defaults (agent mode, IDE, worktrees dir) |
| `kote version` | Print version |

### Tips & Gotchas

- **Run `kote cleanup` from the project root** — the same directory where you ran `kote prep`. Running it from a different directory causes git operations (diff, merge, branch deletion) to target the wrong repository.

- **The agent must commit its changes** — KoteGuard detects what changed by diffing *branch commits* against `main`. If the agent modifies files but never runs `git commit`, those changes do not exist as commits and will not be merged. KoteGuard will block cleanup with a clear error and recovery instructions when this is detected. Use `--force` to skip the block and proceed (the uncommitted changes will not be merged).

- **"No changed files detected" warning** — means the agent branch has no new commits relative to `main`. Check the worktree for uncommitted files before accepting. If the session was already committed and merged manually, this is expected.

- **Find session IDs** — run `kote status` to see all sessions, their IDs, age, and whether the worktree still exists.

---

## Android Skills

KoteGuard bundles best-practice SKILL.md guides that get injected into the agent's context. The scanner auto-detects which ones are relevant based on your `build.gradle`.

| Skill | Triggered by | Guide covers |
|-------|-------------|--------------|
| `navigation3` | `androidx.navigation` dependency | Type-safe NavHost, `@Serializable` routes, no string routes |
| `edge-to-edge` | `enableEdgeToEdge` / API 35 target | `windowInsetsPadding`, `Scaffold` insets, API 35 enforcement |
| `agp9` | AGP 9.x in `libs.versions.toml` | JDK 21 requirement, `namespace`, declarative Kotlin DSL |
| `compose-migration` | `androidx.compose` dependency | State hoisting, `collectAsStateWithLifecycle`, `LazyColumn` keys |

```bash
kote android update   # sync latest skill guides from github.com/android/skills
kote android skills   # see all skills (official + bundled) + what's suggested
kote android docs     # Android developer documentation links
```

KoteGuard also runs a **nightly GitHub Actions workflow** (`.github/workflows/sync-android-skills.yml`) that automatically checks `github.com/android/skills` for updates and opens a PR against `main` whenever skill content changes — so bundled guides stay up to date without any manual work.

---

## iOS Skills

KoteGuard also bundles best-practice guides for iOS/Swift developers. The scanner auto-detects relevant guides based on your Swift source files.

| Skill | Triggered by | Guide covers |
|-------|-------------|--------------|
| `swiftui-patterns` | `import SwiftUI` / `@Observable` | State management, `NavigationStack`, scene lifecycle, performance rules |
| `swift-concurrency` | `async`/`await`/`actor` usage | Structured concurrency, `AsyncStream`, cancellation, `@MainActor` |
| `xctest` | `import XCTest` / `SnapshotTesting` | Async tests, protocol mocking, snapshot testing, performance tests |

```bash
kote ios skills   # see what's available + what's suggested for your project
```

---

## Spec-Driven Development

Every `PLAN.md` KoteGuard creates has a **machine-readable YAML block** at the top. This is the source of truth — not just documentation.

```yaml
---
spec_version: '1.0'
title: Implement login screen
tasks:
- id: t1
  description: Create LoginViewModel
  done: false
- id: t2
  description: Wire up UI
  done: false
definition_of_done:
- All tests pass
- Reviewed
---

# Implement login screen
...
```

**The agent is instructed to update `done: true`** for each task it completes, directly inside that YAML block. When you run `kote cleanup --accept`, KoteGuard:

1. **Parses the YAML** — reads exactly which tasks were marked done
2. **Validates semantically** — checks that changed files actually match each task's keywords (CamelCase-aware: `NavGraph` → searches for `nav`, `graph` in file paths)
3. **Warns if tasks are undone** — if files changed but all tasks are still `done: false`, it flags it
4. **Survives corruption** — if the agent breaks the YAML, a regex fallback recovers the plan silently

This is why PLAN.md is not just a text document — it's a live spec the agent writes back to.

---

## Security Model

KoteGuard is designed so that even a misbehaving agent can't cause lasting damage.

| Layer | Mechanism |
|-------|-----------|
| **Planning gate** | Must type `YES` (or `refine`) — no accidental starts |
| **Branch isolation** | Agent never touches `main` — always a `kote/<id>` branch |
| **Secret stubs** | `google-services.json`, `.jks`, `.p12` etc. swapped for placeholders before the session |
| **Deny-tool flags** | `git push`, `git clone`, `git remote add/set-url` are CLI-level blocked |
| **Dual instructions** | Agent gets both a task brief and a security rules file |
| **Validation on accept** | PLAN.md compliance + file change analysis before any merge |
| **Audit trail** | Every event written to `sessions/<id>/logs/audit.jsonl` + global `~/.kote/audit.jsonl` |
| **History archival** | PLAN, TASK, diff, audit, report copied to `.kote/history/` on every accept or discard |

---

## Generated Copilot CLI Command

`kote cli` prints this — ready to paste:

```bash
cd /path/to/worktree && \
  COPILOT_CUSTOM_INSTRUCTIONS_DIRS=".github/instructions" \
  copilot \
    --deny-tool='shell(git push)' \
    --deny-tool='shell(git remote add)' \
    --deny-tool='shell(git remote set-url)' \
    --deny-tool='shell(git clone)'
```

---

## Project Structure

```
src/koteguard/
├── cli.py              # Typer CLI (kote + kote android subgroup)
├── models.py           # Pydantic v2 models + Android v1.1 skill models
├── config.py           # TOML config · session audit · worktree context check
├── project_scanner.py  # Phase 0: file-signature detection + gradle parsing + doc analysis
├── worktree.py         # Git worktree engine · session subdirs · history archival
├── sensitive_files.py  # Sensitive file stub injection
├── planning.py         # PLAN.md · WORKSPACE.md · Copilot instructions rendering
├── launcher.py         # IDE launcher · build_copilot_cli_command()
├── validation.py       # Plan/change/skills validation · report generation
└── templates.py        # Template file management

templates/
├── PLAN.md                          # Includes Token & Context Rules section
├── WORKSPACE.md                     # Includes Android Agent Stack section
├── TASK.md
├── instructions.md                  # Includes model selection guidance
├── security.instructions.md         # applyTo: "**/*" · Android + iOS deny rules
├── AGENTS.md
├── config.toml
├── android-skills/
│   ├── navigation3.skill.md
│   ├── edge-to-edge.skill.md
│   ├── agp9.skill.md
│   └── compose-migration.skill.md
└── ios-skills/
    ├── swiftui-patterns.skill.md
    ├── swift-concurrency.skill.md
    └── xctest.skill.md
```

---

## Requirements

- Python 3.12+
- Git 2.5+ (for worktree support)
- GitHub Copilot CLI (`copilot` binary) for the terminal workflow
- Android Studio or Xcode (optional, for IDE auto-launch)

---

## Agent Modes

KoteGuard supports three ways to run the Copilot agent. Set the default in `~/.kote/config.toml` or override per session with `kote prep --agent-mode`.

| Mode | How it runs | `kote cli` output |
|------|-------------|-------------------|
| `copilot-cli` *(default)* | Terminal binary with `--deny-tool` security flags | Full copy-pasteable command |
| `copilot-plugin` | IDE chat panel (Android Studio, VS Code) | Open IDE at worktree path |
| `none` | Instructions injected only — bring your own agent | `cd <worktree>` |

**Set defaults interactively:**

```bash
kote init   # guided wizard — sets all fields below
```

**Or edit `~/.kote/config.toml` directly:**

```toml
agent_mode = "copilot-cli"   # copilot-cli | copilot-plugin | none
default_ide = "auto"         # auto | android | ios
android_cli_enabled = true
worktrees_dir = "~/.kote/worktrees"
```

**Override per session:**

```bash
kote prep --agent-mode copilot-plugin
```

---

## Contributing

```bash
git clone https://github.com/alisen/KoteGuard.git
cd KoteGuard
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

---

## License

MIT © [Alishen](https://koteguard.com)
