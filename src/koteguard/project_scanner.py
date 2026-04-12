"""Phase 0 – Smart project analysis (pure Python + stdlib + GitPython)."""

from __future__ import annotations

import plistlib
import re
import time
from pathlib import Path
from typing import Any

from koteguard.models import ProjectInfo, ProjectType

# ---------------------------------------------------------------------------
# Signature files used for project-type detection
# ---------------------------------------------------------------------------

_ANDROID_SIGNATURES = [
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "gradlew",
]
_IOS_SIGNATURES = [".xcodeproj", ".xcworkspace"]
_FLUTTER_SIGNATURES = ["pubspec.yaml"]
_RN_SIGNATURES = ["metro.config.js", "metro.config.ts"]


def _find_files(root: Path, pattern: str, max_depth: int = 3) -> list[Path]:
    """Glob helper with depth cap to stay fast."""
    results: list[Path] = []
    for depth in range(max_depth + 1):
        glob_pat = "/".join(["*"] * depth) + ("/" if depth else "") + pattern
        results.extend(root.glob(glob_pat))
    # Also try a direct match
    results.extend(root.glob(pattern))
    return list(dict.fromkeys(results))  # deduplicate, preserve order


def _has_file(root: Path, name: str, max_depth: int = 3) -> bool:
    return bool(_find_files(root, name, max_depth))


def _has_extension_dir(root: Path, ext: str, max_depth: int = 2) -> bool:
    """Check if any directory with given extension exists (e.g. .xcodeproj)."""
    for depth in range(max_depth + 1):
        prefix = "/".join(["*"] * depth) + ("/" if depth else "")
        if list(root.glob(f"{prefix}*{ext}")):
            return True
    return False


# ---------------------------------------------------------------------------
# Android parsing
# ---------------------------------------------------------------------------


def _parse_build_gradle(path: Path) -> dict[str, Any]:
    """Extract SDK versions and applicationId from build.gradle."""
    info: dict[str, Any] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return info

    patterns = {
        "android_package": r'applicationId\s+["\']([^"\']+)["\']',
        "android_min_sdk": r"minSdk(?:Version)?\s+(\d+)",
        "android_target_sdk": r"targetSdk(?:Version)?\s+(\d+)",
        "android_compile_sdk": r"compileSdk(?:Version)?\s+(\d+)",
    }
    for key, pat in patterns.items():
        m = re.search(pat, text)
        if m:
            val = m.group(1)
            info[key] = int(val) if val.isdigit() else val
    return info


# ---------------------------------------------------------------------------
# iOS parsing
# ---------------------------------------------------------------------------


def _parse_info_plist(path: Path) -> dict[str, Any]:
    """Extract bundle ID and deployment target from Info.plist."""
    info: dict[str, Any] = {}
    try:
        with path.open("rb") as fh:
            plist = plistlib.load(fh)
        info["ios_bundle_id"] = plist.get("CFBundleIdentifier")
        info["ios_deployment_target"] = plist.get(
            "MinimumOSVersion", plist.get("LSMinimumSystemVersion")
        )
    except Exception:
        pass
    return info


# ---------------------------------------------------------------------------
# Flutter parsing
# ---------------------------------------------------------------------------


def _parse_pubspec(path: Path) -> dict[str, Any]:
    """Extract project name and flutter SDK constraint from pubspec.yaml."""
    info: dict[str, Any] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return info

    m = re.search(r"^name:\s*(.+)$", text, re.MULTILINE)
    if m:
        info["project_name"] = m.group(1).strip()

    m = re.search(r"flutter:\s*['\"]?>=?([\d.]+)", text)
    if m:
        info["flutter_sdk"] = m.group(1)
    return info


# ---------------------------------------------------------------------------
# Main scanner
# ---------------------------------------------------------------------------


class ProjectScanner:
    """Analyses a project directory and returns a ProjectInfo."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.cwd()

    def scan(self) -> ProjectInfo:
        """Run all detectors and return a consolidated ProjectInfo."""
        t0 = time.monotonic()

        # Collect signals
        is_android = self._is_android()
        is_ios = self._is_ios()
        is_flutter = self._is_flutter()
        is_rn = self._is_react_native()

        # Determine primary type + confidence
        scores: dict[ProjectType, float] = {}
        if is_flutter:
            scores[ProjectType.FLUTTER] = 0.95
        if is_android and is_ios:
            scores[ProjectType.MONOREPO] = 0.75
        if is_android:
            scores[ProjectType.ANDROID] = 0.90
        if is_ios:
            scores[ProjectType.IOS] = 0.90
        if is_rn:
            scores[ProjectType.REACT_NATIVE] = 0.85

        if not scores:
            project_type = ProjectType.UNKNOWN
            confidence = 0.0
        else:
            project_type = max(scores, key=lambda k: scores[k])
            confidence = scores[project_type]

        info = ProjectInfo(
            project_type=project_type,
            project_name=self._detect_project_name(project_type),
            root=self.root,
            confidence=confidence,
            has_tests=self._has_tests(),
            has_ci=self._has_ci(),
            languages=self._detect_languages(),
            frameworks=self._detect_frameworks(project_type),
            sub_projects=self._detect_sub_projects(),
        )

        # Type-specific enrichment
        if project_type in (ProjectType.ANDROID, ProjectType.MONOREPO):
            info = self._enrich_android(info)
        if project_type in (ProjectType.IOS, ProjectType.MONOREPO):
            info = self._enrich_ios(info)
        if project_type == ProjectType.FLUTTER:
            info = self._enrich_flutter(info)

        elapsed = (time.monotonic() - t0) * 1000
        # Target < 600 ms – just record, don't raise
        _ = elapsed
        return info

    # ------------------------------------------------------------------
    # Detectors
    # ------------------------------------------------------------------

    def _is_android(self) -> bool:
        return any(
            _has_file(self.root, sig)
            for sig in _ANDROID_SIGNATURES
            if not sig.startswith(".")
        )

    def _is_ios(self) -> bool:
        return any(_has_extension_dir(self.root, ext) for ext in _IOS_SIGNATURES)

    def _is_flutter(self) -> bool:
        return _has_file(self.root, "pubspec.yaml")

    def _is_react_native(self) -> bool:
        return any(_has_file(self.root, sig) for sig in _RN_SIGNATURES)

    def _has_tests(self) -> bool:
        test_dirs = {"test", "tests", "androidTest", "iosTest", "__tests__"}
        # Check at root level first (fast path)
        if any((self.root / d).is_dir() for d in test_dirs):
            return True
        # Check nested (e.g. app/src/androidTest)
        for sub in self.root.rglob("*"):
            if sub.is_dir() and sub.name in test_dirs:
                return True
        return False

    def _has_ci(self) -> bool:
        ci_paths = [
            ".github/workflows",
            ".circleci",
            ".travis.yml",
            "bitrise.yml",
            "Jenkinsfile",
            ".gitlab-ci.yml",
            "Fastfile",
        ]
        return any((self.root / p).exists() for p in ci_paths)

    def _detect_languages(self) -> list[str]:
        langs: list[str] = []
        ext_map = {
            ".kt": "Kotlin",
            ".java": "Java",
            ".swift": "Swift",
            ".dart": "Dart",
            ".ts": "TypeScript",
            ".tsx": "TypeScript",
            ".js": "JavaScript",
            ".jsx": "JavaScript",
            ".py": "Python",
        }
        found: set[str] = set()
        for path in self.root.rglob("*"):
            if path.suffix in ext_map and ext_map[path.suffix] not in found:
                # Skip vendor / build dirs
                parts = set(path.parts)
                if parts & {"node_modules", "build", ".gradle", "Pods", ".pub-cache"}:
                    continue
                found.add(ext_map[path.suffix])
        langs = sorted(found)
        return langs

    def _detect_frameworks(self, project_type: ProjectType) -> list[str]:
        frameworks: list[str] = []
        if project_type == ProjectType.ANDROID:
            frameworks.append("Android SDK")
            if _has_file(self.root, "build.gradle") or _has_file(
                self.root, "build.gradle.kts"
            ):
                frameworks.append("Gradle")
            if _has_file(self.root, "compose.gradle") or _has_file(
                self.root, "compose.gradle.kts"
            ):
                frameworks.append("Jetpack Compose")
        elif project_type == ProjectType.IOS:
            frameworks.append("UIKit/SwiftUI")
            if (self.root / "Podfile").exists():
                frameworks.append("CocoaPods")
            if (self.root / "Package.swift").exists():
                frameworks.append("Swift Package Manager")
        elif project_type == ProjectType.FLUTTER:
            frameworks.append("Flutter")
        elif project_type == ProjectType.REACT_NATIVE:
            frameworks.append("React Native")
        return frameworks

    def _detect_project_name(self, project_type: ProjectType) -> str:
        # Try pubspec first (Flutter)
        pubspec = self.root / "pubspec.yaml"
        if pubspec.exists():
            data = _parse_pubspec(pubspec)
            if data.get("project_name"):
                return data["project_name"]
        # Fallback: directory name
        return self.root.name

    def _detect_sub_projects(self) -> list[str]:
        """Detect module/sub-project directories."""
        subs: list[str] = []
        for child in self.root.iterdir():
            if not child.is_dir():
                continue
            if child.name.startswith("."):
                continue
            if (child / "build.gradle").exists() or (
                child / "build.gradle.kts"
            ).exists():
                subs.append(child.name)
        return subs

    # ------------------------------------------------------------------
    # Enrichment
    # ------------------------------------------------------------------

    def _enrich_android(self, info: ProjectInfo) -> ProjectInfo:
        # Find the app module build.gradle
        candidates = list(self.root.rglob("build.gradle")) + list(
            self.root.rglob("build.gradle.kts")
        )
        for candidate in candidates:
            data = _parse_build_gradle(candidate)
            if data:
                info.android_package = data.get("android_package")
                info.android_min_sdk = data.get("android_min_sdk")
                info.android_target_sdk = data.get("android_target_sdk")
                info.android_compile_sdk = data.get("android_compile_sdk")
                if info.android_package:
                    break
        return info

    def _enrich_ios(self, info: ProjectInfo) -> ProjectInfo:
        for plist_path in self.root.rglob("Info.plist"):
            data = _parse_info_plist(plist_path)
            if data.get("ios_bundle_id"):
                info.ios_bundle_id = data["ios_bundle_id"]
                info.ios_deployment_target = data.get("ios_deployment_target")
                break
        return info

    def _enrich_flutter(self, info: ProjectInfo) -> ProjectInfo:
        pubspec = self.root / "pubspec.yaml"
        if pubspec.exists():
            data = _parse_pubspec(pubspec)
            info.flutter_sdk = data.get("flutter_sdk")
        return info
