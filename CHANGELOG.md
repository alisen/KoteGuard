# Changelog

All notable changes to KoteGuard are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.0.0a5] – 2026-04-23

### Added
- **Logo** – `koteguard.png` displayed at the top of README
- **`kote init`** – interactive wizard to configure global defaults (agent mode, IDE, Android CLI, worktrees dir)
- **`kote sessions prune`** – remove stale session metadata older than N days; supports `--dry-run`
- **`kote ios skills`** – mirrors `kote android skills`; lists bundled SwiftUI, Swift Concurrency, and XCTest skill guides
- **`kote android update`** – syncs official skill guides from `github.com/android/skills` into a user-level cache (`~/.kote/android-skills/`)
- **`kote android skills` Source column** – shows whether each skill came from the official cache or the bundled fallback
- **Nightly sync workflow** (`.github/workflows/sync-android-skills.yml`) – runs at 02:00 UTC, diffs official skills against bundled templates, and opens a PR if anything changed
- **Plan column in `kote status`** – shows truncated plan title so sessions are immediately identifiable
- **iOS skill guides** – `swiftui-patterns`, `swift-concurrency`, `xctest` added to `templates/ios-skills/`
- **`.env` stub** – `.env` files are now included in sensitive-file stubs for both Android and iOS projects
- **CI: ruff format check** – `ruff format --check` added to the CI pipeline
- **CI: coverage enforcement** – pytest runs with `--cov-fail-under=88` (total 90%+)

### Fixed
- **`list_sessions()` sort order** – sessions were sorted by UUID string; now correctly sorted by `created_at` so `kote cleanup` and `kote cli` always target the _most recent_ session
- **`--compact` workspace path** – session summaries now write to the project-local `.kote/WORKSPACE.md` (copied into future worktrees) instead of the unreachable `~/.kote/WORKSPACE.md`
- **`validate` exit code** – workspace validation failures now correctly exit 1 instead of 0
- **Silent exceptions in `prep`** – TASK.md / AGENTS.md write failures now print a `[yellow]` warning instead of silently disappearing

### Changed
- **CI actions pinned to latest** – all four workflows use `actions/checkout@v6` and `actions/setup-python@v6` consistently
- **`kote android skills`** – prefers user-synced skills from `~/.kote/android-skills/` over bundled fallbacks
- **Coverage threshold** raised from 60% → 88%

### Tests
- Added `tests/test_models.py`, `tests/test_planning.py`, `tests/test_config.py`, `tests/test_worktree.py`, `tests/test_sensitive_files.py`, `tests/test_launcher.py`, `tests/test_project_scanner.py`, `tests/test_cli.py`, `tests/test_cli_extended.py`, `tests/test_cli_interactive.py`
- **575 tests total, 90% total coverage** (`cli.py` from 39% → 87%)

---

## [1.0.0a4] – 2026-04-19

### Added
- Block `kote cleanup --accept` when agent left uncommitted changes in the worktree; `--force` overrides
- Fix repo targeting so `_git.Repo` always resolves from `project_root`, not `worktree_path`

### Changed
- CodeQL upgraded to v4; GitHub Actions security scanning added
- Dependabot groups squashed; CONTRIBUTING.md and PR template added

---

## [1.0.0a3] – 2026-04-14

### Added
- Android Skills: bundled SKILL.md guides for Navigation 3, Edge-to-Edge, AGP 9, Compose migration
- `kote android skills` – list and suggest skills based on project scan
- `kote android docs` – quick reference for detected Android version
- `--android-first` flag on `kote prep` – skills checkbox before planning loop

### Fixed
- `kote version` now shows correct installed version via `importlib.metadata`

---

## [1.0.0a2] – 2026-04-08

### Added
- Full `kote prep` interactive wizard: project scan → plan → worktree → IDE launch
- `kote ide` and `kote cli` fast-path commands
- Sensitive file stub injection for Android (`.jks`, `google-services.json`, etc.)
- `ProjectScanner` with Android/iOS project type detection

---

## [1.0.0a1] – 2026-04-01

### Added
- Initial release: `kote prep`, `kote cleanup`, `kote status`, `kote validate`
- Git worktree isolation via `WorktreeEngine`
- Pydantic models for `SessionMeta`, `PlanModel`, `TaskModel`, `WorkspaceModel`
- PLAN.md / TASK.md / AGENTS.md / WORKSPACE.md template rendering
