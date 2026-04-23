"""Git worktree engine – create, list, and tear down agent worktrees."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import git

from koteguard.config import (
    SESSIONS_DIR,
    WORKTREES_DIR,  # noqa: F401 — imported for test-patching
    append_audit,  # noqa: F401 — imported for test-patching
    append_session_audit,
    load_global_config,
)
from koteguard.models import AgentMode, SessionMeta, SessionStatus


def _slugify(text: str) -> str:
    """Convert arbitrary string to a safe directory slug."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text[:40] or "project"


def _session_meta_path(session_id: str) -> Path:
    return SESSIONS_DIR / session_id / "meta.json"


def load_session(session_id: str) -> SessionMeta | None:
    """Load a session from ~/.kote/sessions/<id>/meta.json."""
    path = _session_meta_path(session_id)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return SessionMeta.model_validate(data)


def save_session(meta: SessionMeta) -> None:
    """Persist session metadata."""
    path = _session_meta_path(meta.session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(meta.model_dump(mode="json"), indent=2, default=str),
        encoding="utf-8",
    )


def list_sessions() -> list[SessionMeta]:
    """Return all known sessions, sorted by created_at ascending (oldest first)."""
    sessions: list[SessionMeta] = []
    if not SESSIONS_DIR.exists():
        return sessions
    for session_dir in SESSIONS_DIR.iterdir():
        meta_file = session_dir / "meta.json"
        if meta_file.exists():
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                sessions.append(SessionMeta.model_validate(data))
            except Exception:
                pass
    # Sort by created_at so active[-1] always returns the most recently created session.
    # Folder names are random UUIDs — alphabetical order has no time relationship.
    sessions.sort(key=lambda s: s.created_at)
    return sessions


class WorktreeEngine:
    """Creates and manages isolated git worktrees for agent sessions."""

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or Path.cwd()

    def _get_repo(self) -> git.Repo:
        return git.Repo(self.project_root, search_parent_directories=True)

    def create_worktree(
        self,
        task_description: str = "agent-task",
        session_id: str | None = None,
        base_branch: str | None = None,
        plan_title: str = "",
        agent_mode: AgentMode = AgentMode.COPILOT_CLI,
    ) -> SessionMeta:
        """
        Create a new git worktree for an agent session.

        Returns a populated SessionMeta.
        """
        cfg = load_global_config()
        repo = self._get_repo()
        project_root = Path(repo.working_tree_dir)

        if not session_id:
            session_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
        project_slug = _slugify(project_root.name)
        branch_name = f"kote/{session_id}-{_slugify(task_description)[:30]}"

        worktree_path = Path(cfg.worktrees_dir) / project_slug / f"{session_id}-{timestamp}"
        worktree_path.parent.mkdir(parents=True, exist_ok=True)

        if base_branch is None:
            if repo.head.is_detached:
                base_branch = "HEAD"
            else:
                base_branch = repo.active_branch.name

        repo.git.worktree("add", "-b", branch_name, str(worktree_path), base_branch)

        meta = SessionMeta(
            session_id=session_id,
            project_slug=project_slug,
            project_root=project_root,
            worktree_path=worktree_path,
            branch_name=branch_name,
            status=SessionStatus.ACTIVE,
            plan_title=plan_title or task_description,
            agent_mode=agent_mode,
        )
        save_session(meta)

        # Create session subdirectory structure
        self._create_session_dirs(session_id)

        first_entry: dict[str, Any] = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "event": "session_created",
            "session_id": session_id,
            "details": {
                "branch": branch_name,
                "worktree_path": str(worktree_path),
                "project_root": str(project_root),
                "plan_title": plan_title,
            },
        }
        append_session_audit(session_id, first_entry)

        return meta

    def _create_session_dirs(self, session_id: str) -> None:
        """Create context/, logs/, output/ subdirs for a session."""
        for subdir in ("context", "logs", "output"):
            (SESSIONS_DIR / session_id / subdir).mkdir(parents=True, exist_ok=True)

    def copy_context_files(
        self,
        session_id: str,
        files: dict[str, Path],
    ) -> None:
        """Copy plan/task/instruction files into sessions/{id}/context/."""
        context_dir = SESSIONS_DIR / session_id / "context"
        context_dir.mkdir(parents=True, exist_ok=True)
        for dest_name, src_path in files.items():
            if src_path.exists():
                try:
                    shutil.copy2(src_path, context_dir / dest_name)
                except Exception:
                    pass

    def accept_worktree(
        self,
        session_id: str,
        force: bool = False,
    ) -> bool:
        """
        Accept changes: merge back to project root, archive history, remove worktree.
        """
        meta = load_session(session_id)
        if not meta:
            return False

        worktree_path = Path(meta.worktree_path)
        project_root = Path(meta.project_root)

        history_dir = self._history_dir(project_root, session_id)
        history_dir.mkdir(parents=True, exist_ok=True)

        # Generate and copy diff/patch
        patch_content = ""
        try:
            repo = git.Repo(project_root, search_parent_directories=True)
            try:
                patch_content = repo.git.diff(f"HEAD...{meta.branch_name}")
                (history_dir / "changes.diff").write_text(patch_content, encoding="utf-8")
            except git.GitCommandError:
                pass

            # Merge branch
            try:
                repo.git.merge(
                    meta.branch_name,
                    "--no-ff",
                    "-m",
                    f"feat(kote/{session_id}): accept agent changes",
                )
            except git.GitCommandError:
                pass
        except Exception:
            pass

        # Archive context files to history
        self._archive_accept(session_id, worktree_path, history_dir)
        self._remove_worktree(meta)

        meta.status = SessionStatus.COMPLETED
        meta.completed_at = datetime.now(tz=UTC)
        save_session(meta)

        entry: dict[str, Any] = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "event": "worktree_accepted",
            "session_id": session_id,
            "details": {"history_dir": str(history_dir)},
        }
        append_session_audit(session_id, entry)
        return True

    def discard_worktree(self, session_id: str) -> bool:
        """Discard all changes and remove the worktree."""
        meta = load_session(session_id)
        if not meta:
            return False

        project_root = Path(meta.project_root)

        # Archive audit trail on discard too
        history_dir = self._history_dir(project_root, session_id)
        self._archive_discard(session_id, history_dir)

        self._remove_worktree(meta)

        meta.status = SessionStatus.DISCARDED
        meta.completed_at = datetime.now(tz=UTC)
        save_session(meta)

        entry: dict[str, Any] = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "event": "worktree_discarded",
            "session_id": session_id,
        }
        append_session_audit(session_id, entry)
        return True

    def _archive_accept(
        self,
        session_id: str,
        worktree_path: Path,
        history_dir: Path,
    ) -> None:
        """Copy PLAN.md, TASK.md, audit.jsonl, validation-report.md to history."""
        history_dir.mkdir(parents=True, exist_ok=True)

        # Files from worktree
        for fname in ("PLAN.md", "TASK.md"):
            src = worktree_path / fname
            if src.exists():
                try:
                    shutil.copy2(src, history_dir / fname)
                except Exception:
                    pass

        # Per-session audit log
        from koteguard.config import SESSIONS_DIR as _SESSIONS_DIR

        audit_src = _SESSIONS_DIR / session_id / "logs" / "audit.jsonl"
        if audit_src.exists():
            try:
                shutil.copy2(audit_src, history_dir / "audit.jsonl")
            except Exception:
                pass

        # Validation report (if generated)
        report_src = _SESSIONS_DIR / session_id / "output" / "validation-report.md"
        if report_src.exists():
            try:
                shutil.copy2(report_src, history_dir / "validation-report.md")
            except Exception:
                pass

    def _archive_discard(self, session_id: str, history_dir: Path) -> None:
        """On discard: copy PLAN.md + audit.jsonl only."""
        from koteguard.config import SESSIONS_DIR as _SESSIONS_DIR

        history_dir.mkdir(parents=True, exist_ok=True)

        # Try to get PLAN.md from the session context
        plan_src = _SESSIONS_DIR / session_id / "context" / "PLAN.md"
        if plan_src.exists():
            try:
                shutil.copy2(plan_src, history_dir / "PLAN.md")
            except Exception:
                pass

        audit_src = _SESSIONS_DIR / session_id / "logs" / "audit.jsonl"
        if audit_src.exists():
            try:
                shutil.copy2(audit_src, history_dir / "audit.jsonl")
            except Exception:
                pass

    def _remove_worktree(self, meta: SessionMeta) -> None:
        """Prune worktree and delete branch."""
        worktree_path = Path(meta.worktree_path)
        project_root = Path(meta.project_root)
        try:
            repo = git.Repo(project_root, search_parent_directories=True)
            repo.git.worktree("remove", "--force", str(worktree_path))
        except Exception:
            if worktree_path.exists():
                shutil.rmtree(worktree_path, ignore_errors=True)
            try:
                repo = git.Repo(project_root, search_parent_directories=True)
                repo.git.worktree("prune")
            except Exception:
                pass

        try:
            repo = git.Repo(project_root, search_parent_directories=True)
            repo.git.branch("-D", meta.branch_name)
        except Exception:
            pass

    def _history_dir(self, project_root: Path, session_id: str) -> Path:
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
        slug = _slugify(session_id)
        return project_root / ".kote" / "history" / f"{timestamp}-{slug}"
