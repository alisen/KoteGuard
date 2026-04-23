"""Phase 4 – IDE and CLI launcher."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

from koteguard.models import AgentMode, IDEChoice

# ---------------------------------------------------------------------------
# IDE detection helpers
# ---------------------------------------------------------------------------

_ANDROID_STUDIO_BINARY_NAMES = [
    "studio",
    "studio.sh",
    "studio64.exe",
    "android-studio",
]

_ANDROID_STUDIO_PATHS = [
    "/opt/android-studio/bin/studio.sh",
    "/usr/local/android-studio/bin/studio.sh",
    str(Path.home() / "android-studio" / "bin" / "studio.sh"),
    str(Path.home() / "Applications" / "Android Studio.app" / "Contents" / "MacOS" / "studio"),
    "/Applications/Android Studio.app/Contents/MacOS/studio",
    str(
        Path.home()
        / "Applications"
        / "Android Studio Preview.app"
        / "Contents"
        / "MacOS"
        / "studio"
    ),
    "/Applications/Android Studio Preview.app/Contents/MacOS/studio",
]

_XCODE_BINARY_NAMES = ["xed"]
_XCODE_PATHS = ["/Applications/Xcode.app/Contents/MacOS/Xcode"]

# Deny-list for Copilot CLI security
_DENY_TOOLS = [
    "shell(git push)",
    "shell(git remote add)",
    "shell(git remote set-url)",
    "shell(git clone)",
]


def detect_android_studio() -> str | None:
    """Return path to Android Studio binary, or None if not found."""
    for name in _ANDROID_STUDIO_BINARY_NAMES:
        if path := shutil.which(name):
            return path
    for path_str in _ANDROID_STUDIO_PATHS:
        if Path(path_str).is_file():
            return path_str
    if platform.system() == "Darwin":
        try:
            result = subprocess.run(
                ["osascript", "-e", 'return POSIX path of (path to application "Android Studio")'],
                capture_output=True,
                text=True,
                timeout=3,
            )
            candidate = result.stdout.strip().rstrip("/") + "/Contents/MacOS/studio"
            if Path(candidate).is_file():
                return candidate
        except Exception:
            pass
    return None


def detect_xcode() -> str | None:
    """Return path to Xcode binary (xed), or None if not found."""
    for name in _XCODE_BINARY_NAMES:
        if path := shutil.which(name):
            return path
    for path_str in _XCODE_PATHS:
        if Path(path_str).is_file():
            return path_str
    return None


def pick_ide(ide_choice: IDEChoice, worktree_path: Path) -> str | None:
    """
    Determine the IDE binary to launch based on user preference and detection.
    """
    choice = ide_choice if isinstance(ide_choice, str) else ide_choice.value

    if choice == "android":
        return detect_android_studio()
    if choice == "ios":
        return detect_xcode()

    android_binary = detect_android_studio()
    xcode_binary = detect_xcode()

    has_gradle = any(worktree_path.rglob("build.gradle*"))
    has_xcode = (
        any(p for p in worktree_path.iterdir() if p.suffix in (".xcodeproj", ".xcworkspace"))
        if worktree_path.exists()
        else False
    )

    if has_gradle and android_binary:
        return android_binary
    if has_xcode and xcode_binary:
        return xcode_binary
    return android_binary or xcode_binary


def build_copilot_cli_command(
    worktree_path: Path,
    agent_mode: AgentMode = AgentMode.COPILOT_CLI,
) -> str | None:
    """
    Build a complete, copy-pasteable Copilot CLI command with deny-tool flags
    and COPILOT_CUSTOM_INSTRUCTIONS_DIRS env var.

    Returns None for non-CLI agent modes (copilot-plugin, none).
    """
    if agent_mode != AgentMode.COPILOT_CLI:
        return None

    deny_flags = " ".join(f"--deny-tool='{tool}'" for tool in _DENY_TOOLS)
    instructions_dir = ".github/instructions"

    return (
        f"cd {worktree_path} && "
        f'COPILOT_CUSTOM_INSTRUCTIONS_DIRS="{instructions_dir}" '
        f"copilot {deny_flags}"
    )


class IDELauncher:
    """Launches an IDE or terminal at the worktree path."""

    def __init__(self, worktree_path: Path) -> None:
        self.worktree_path = worktree_path

    def launch_ide(self, ide_choice: IDEChoice = IDEChoice.AUTO) -> bool:
        """Launch the IDE and open the worktree. Returns True if launched."""
        binary = pick_ide(ide_choice, self.worktree_path)
        if not binary:
            return False

        args = [binary]
        bin_name = Path(binary).name.lower()
        if "studio" in bin_name or "android" in bin_name:
            args.append(str(self.worktree_path))
        elif bin_name == "xed":
            args.append(str(self.worktree_path))

        subprocess.Popen(  # noqa: S603
            args,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True

    def open_terminal(self) -> bool:
        """Open a terminal at the worktree path with COPILOT_CUSTOM_INSTRUCTIONS_DIRS set."""
        system = platform.system()
        env = os.environ.copy()
        env["COPILOT_CUSTOM_INSTRUCTIONS_DIRS"] = ".github/instructions"

        try:
            if system == "Darwin":
                subprocess.Popen(  # noqa: S603
                    ["open", "-a", "Terminal", str(self.worktree_path)],
                    start_new_session=True,
                    env=env,
                )
            elif system == "Linux":
                for term in ("gnome-terminal", "xterm", "konsole", "xfce4-terminal"):
                    if shutil.which(term):
                        subprocess.Popen(  # noqa: S603
                            [term, "--working-directory", str(self.worktree_path)],
                            start_new_session=True,
                            env=env,
                        )
                        break
            elif system == "Windows":
                subprocess.Popen(  # noqa: S603
                    ["cmd", "/c", "start", "cmd", "/k", f"cd /d {self.worktree_path}"],
                    start_new_session=True,
                    env=env,
                )
            return True
        except Exception:
            return False

    def print_cd_command(self) -> str:
        """Return a shell command the user can copy to cd into the worktree."""
        return f"cd {self.worktree_path}"
