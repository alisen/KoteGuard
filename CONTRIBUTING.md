# Contributing to KoteGuard

Thanks for your interest! KoteGuard welcomes contributions via **fork + pull request** — no collaborator access needed.

## How to contribute

### 1. Fork the repo

Click **Fork** on [github.com/alisen/KoteGuard](https://github.com/alisen/KoteGuard).

### 2. Clone your fork and set up

```bash
git clone https://github.com/YOUR_USERNAME/KoteGuard.git
cd KoteGuard
pip install -e ".[dev]"
```

### 3. Create a branch

```bash
git checkout -b fix/your-fix-name
# or
git checkout -b feat/your-feature-name
```

### 4. Make your changes

- Keep changes focused — one PR per fix or feature
- Add or update tests for your change
- Run tests and lint before pushing:

```bash
pytest
ruff check src/ tests/
```

### 5. Push and open a PR

```bash
git push origin your-branch-name
```

Then open a Pull Request against `alisen/KoteGuard` → `main`.

---

## What to work on

Check [open issues](https://github.com/alisen/KoteGuard/issues) — anything labelled `good first issue` or `help wanted` is a good starting point.

## Code style

- Python 3.12+
- Ruff for linting (config in `pyproject.toml`)
- Pydantic v2 models for all data structures
- Tests go in `tests/` — pytest, no mocking of core logic unless necessary

## Commit messages

Use a short prefix:
- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation only
- `test:` — tests only
- `chore:` — tooling, dependencies

Example: `feat: add swift package manager detection`
