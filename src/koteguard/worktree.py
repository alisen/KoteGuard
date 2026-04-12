"""Git worktree engine – create, list, and tear down agent worktrees."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import git

from koteguard.config import (
    SESSIONS_DIR,
    WORKTREES_DIR,
    append_audit,
    load_global_config,
)
from koteguard.models import SessionMeta, SessionStatus


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
    """Return all known sessions."""
    sessions: list[SessionMeta] = []
    if not SESSIONS_DIR.exists():
        return sessions
    for session_dir in sorted(SESSIONS_DIR.iterdir()):
        meta_file = session_dir / "meta.json"
        if meta_file.exists():
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                sessions.append(SessionMeta.model_validate(data))
            except Exception:
                pass
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
    ) -> SessionMeta:
        """
        Create a new git worktree for an agent session.

        Returns a populated SessionMeta.
        """
        cfg = load_global_config()
        repo = self._get_repo()
        project_root = Path(repo.working_tree_dir)

        # Generate IDs
        if not session_id:
            session_id = str(uuid.uuid4())[:8]
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        project_slug = _slugify(project_root.name)
        branch_name = f"kote/{session_id}-{_slugify(task_description)[:30]}"

        # Worktree path
        worktree_path = (
            Path(cfg.worktrees_dir) / project_slug / f"{session_id}-{timestamp}"
        )
        worktree_path.parent.mkdir(parents=True, exist_ok=True)

        # Determine base
        if base_branch is None:
            try:
                base_branch = repo.active_branch.name
            except TypeError:
                base_branch = "HEAD"

        # Create branch + worktree
        repo.git.worktree("add", "-b", branch_name, str(worktree_path), base_branch)

        meta = SessionMeta(
            session_id=session_id,
            project_slug=project_slug,
            project_root=project_root,
            worktree_path=worktree_path,
            branch_name=branch_name,
            status=SessionStatus.ACTIVE,
        )
        save_session(meta)

        append_audit(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "event": "worktree_created",
                "session_id": session_id,
                "details": {
                    "branch": branch_name,
                    "worktree_path": str(worktree_path),
                    "project_root": str(project_root),
                },
            }
        )
        return meta

    def accept_worktree(self, session_id: str) -> bool:
        """
        Accept changes: copy modified files back to the project root,
        record history, remove the worktree.
        """
        meta = load_session(session_id)
        if not meta:
            return False

        worktree_path = Path(meta.worktree_path)
        project_root = Path(meta.project_root)

        # Save to project history
        history_dir = self._history_dir(project_root, session_id)
        history_dir.mkdir(parents=True, exist_ok=True)

        # Copy changed files (via git diff) to history for reference
        try:
            repo = self._get_repo()
            diff_output = repo.git.diff(
                f"{meta.branch_name}...HEAD", "--name-only"
            )
            # Save patch
            try:
                patch = repo.git.diff(f"HEAD...{meta.branch_name}")
                (history_dir / "changes.patch").write_text(patch, encoding="utf-8")
            except git.GitCommandError:
                pass

            # Merge branch into main
            try:
                repo.git.merge(
                    meta.branch_name,
                    "--no-ff",
                    "-m",
                    f"feat(kote/{session_id}): accept agent changes",
                )
            except git.GitCommandError:
                # If merge fails, just record and remove
                pass
        except Exception:
            pass

        self._remove_worktree(meta)

        meta.status = SessionStatus.COMPLETED
        meta.completed_at = datetime.utcnow()
        save_session(meta)

        append_audit(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "event": "worktree_accepted",
                "session_id": session_id,
            }
        )
        return True

    def discard_worktree(self, session_id: str) -> bool:
        """Discard all changes and remove the worktree."""
        meta = load_session(session_id)
        if not meta:
            return False

        self._remove_worktree(meta)

        meta.status = SessionStatus.DISCARDED
        meta.completed_at = datetime.utcnow()
        save_session(meta)

        append_audit(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "event": "worktree_discarded",
                "session_id": session_id,
            }
        )
        return True

    def _remove_worktree(self, meta: SessionMeta) -> None:
        """Prune worktree and delete branch."""
        worktree_path = Path(meta.worktree_path)
        try:
            repo = self._get_repo()
            repo.git.worktree("remove", "--force", str(worktree_path))
        except Exception:
            # Fallback: manual removal
            if worktree_path.exists():
                shutil.rmtree(worktree_path, ignore_errors=True)
            try:
                repo = self._get_repo()
                repo.git.worktree("prune")
            except Exception:
                pass

        # Delete the branch
        try:
            repo = self._get_repo()
            repo.git.branch("-D", meta.branch_name)
        except Exception:
            pass

    def _history_dir(self, project_root: Path, session_id: str) -> Path:
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        slug = _slugify(session_id)
        return project_root / ".kote" / "history" / f"{timestamp}-{slug}"
