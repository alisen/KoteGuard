"""Template file management – copy bundled templates to target locations."""

from __future__ import annotations

from pathlib import Path
from string import Template

# Bundled templates live next to the package's pyproject.toml
_REPO_TEMPLATES = Path(__file__).parent.parent.parent / "templates"
_INSTALLED_TEMPLATES = Path(__file__).parent / "templates"


def _templates_dir() -> Path:
    """Return the templates directory, checking installed location first."""
    if _INSTALLED_TEMPLATES.exists():
        return _INSTALLED_TEMPLATES
    if _REPO_TEMPLATES.exists():
        return _REPO_TEMPLATES
    raise FileNotFoundError(
        f"Templates directory not found. Checked:\n  {_INSTALLED_TEMPLATES}\n  {_REPO_TEMPLATES}"
    )


def get_template(name: str) -> str:
    """Read a template file and return its contents."""
    path = _templates_dir() / name
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {name}")
    return path.read_text(encoding="utf-8")


def render_template(name: str, **kwargs: str) -> str:
    """Read and render a template with $variable substitution."""
    content = get_template(name)
    return Template(content).safe_substitute(**kwargs)


def write_template(name: str, dest: Path, **kwargs: str) -> Path:
    """Render a template and write it to *dest*."""
    content = render_template(name, **kwargs)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    return dest


def list_templates() -> list[str]:
    """Return names of all available templates."""
    return [p.name for p in sorted(_templates_dir().iterdir()) if p.is_file()]


def install_templates_to(target_dir: Path) -> list[Path]:
    """Copy all bundled templates to *target_dir*."""
    target_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for src in sorted(_templates_dir().iterdir()):
        if src.is_file():
            dest = target_dir / src.name
            dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            written.append(dest)
    return written
