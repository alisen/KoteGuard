"""Phase 0 – Smart project analysis (pure Python + stdlib + GitPython)."""

from __future__ import annotations

import plistlib
import re
import shutil
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

# ---------------------------------------------------------------------------
# Android skill detection keywords in build.gradle
# ---------------------------------------------------------------------------

_SKILL_KEYWORDS: dict[str, list[str]] = {
    "navigation3": ["androidx.navigation", "navigation-compose", "NavHost"],
    "edge-to-edge": [
        "WindowCompat.setDecorFitsSystemWindows",
        "enableEdgeToEdge",
        "edge-to-edge",
    ],
    "agp9": ["com.android.tools.build:gradle:9", "agp9", "8.0", "AGP 9"],
    "compose-migration": [
        "androidx.compose",
        "jetpack compose",
        "composable",
        "ComposeView",
    ],
}

_AGENT_KEYWORDS = ["agent", "copilot", "ai assistant", "llm", "cursor", "firebender"]


def _find_files(root: Path, pattern: str, max_depth: int = 4) -> list[Path]:
    """Glob helper with depth cap to stay fast."""
    results: list[Path] = []
    for depth in range(max_depth + 1):
        glob_pat = "/".join(["*"] * depth) + ("/" if depth else "") + pattern
        results.extend(root.glob(glob_pat))
    results.extend(root.glob(pattern))
    return list(dict.fromkeys(results))  # deduplicate, preserve order


def _has_file(root: Path, name: str, max_depth: int = 4) -> bool:
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
# Main scanner
# ---------------------------------------------------------------------------


class ProjectScanner:
    """Analyses a project directory and returns a ProjectInfo."""

    def __init__(self, root: Path | None = None, android_cli_enabled: bool = True) -> None:
        self.root = root or Path.cwd()
        self._android_cli_enabled = android_cli_enabled

    def scan(self) -> ProjectInfo:
        """Run all detectors and return a consolidated ProjectInfo."""
        t0 = time.monotonic()

        is_android = self._is_android()
        is_ios = self._is_ios()

        scores: dict[ProjectType, float] = {}
        if is_android and is_ios:
            scores[ProjectType.MONOREPO] = 0.75
        if is_android:
            scores[ProjectType.ANDROID] = 0.90
        if is_ios:
            scores[ProjectType.IOS] = 0.90

        if not scores:
            project_type = ProjectType.UNKNOWN
            confidence = 0.0
        else:
            project_type = max(scores, key=lambda k: scores[k])
            confidence = scores[project_type]

        info = ProjectInfo(
            project_type=project_type,
            project_name=self._detect_project_name(),
            root=self.root,
            confidence=confidence,
            has_tests=self._has_tests(),
            has_ci=self._has_ci(),
            languages=self._detect_languages(),
            frameworks=self._detect_frameworks(project_type),
            sub_projects=self._detect_sub_projects(),
            android_cli_available=self._detect_android_cli(),
            detected_skills=self._scan_for_skills(),
            doc_summary=self._analyze_documentation(),
        )

        if project_type in (ProjectType.ANDROID, ProjectType.MONOREPO):
            info = self._enrich_android(info)
        if project_type in (ProjectType.IOS, ProjectType.MONOREPO):
            info = self._enrich_ios(info)

        # Auto-suggest skills based on project features
        info.detected_skills = list(
            set(info.detected_skills) | set(self._suggest_skills(info))
        )

        elapsed = (time.monotonic() - t0) * 1000
        info.elapsed_ms = elapsed
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

    def _has_tests(self) -> bool:
        test_dirs = {"test", "tests", "androidTest", "iosTest", "__tests__"}
        if any((self.root / d).is_dir() for d in test_dirs):
            return True
        # Depth-capped search (max 4 levels)
        for depth in range(1, 5):
            pattern = "/".join(["*"] * depth)
            for sub in self.root.glob(pattern):
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
        ext_map = {
            ".kt": "Kotlin",
            ".java": "Java",
            ".swift": "Swift",
            ".ts": "TypeScript",
            ".tsx": "TypeScript",
            ".js": "JavaScript",
            ".jsx": "JavaScript",
            ".py": "Python",
        }
        found: set[str] = set()
        # Depth-capped glob (max 4 levels)
        for depth in range(1, 5):
            pattern = "/".join(["*"] * depth)
            for path in self.root.glob(pattern):
                if path.suffix in ext_map and ext_map[path.suffix] not in found:
                    parts = set(path.parts)
                    if parts & {"node_modules", "build", ".gradle", "Pods"}:
                        continue
                    found.add(ext_map[path.suffix])
        return sorted(found)

    def _detect_frameworks(self, project_type: ProjectType) -> list[str]:
        frameworks: list[str] = []
        if project_type == ProjectType.ANDROID:
            frameworks.append("Android SDK")
            if _has_file(self.root, "build.gradle") or _has_file(
                self.root, "build.gradle.kts"
            ):
                frameworks.append("Gradle")
            # Check for Compose usage
            gradle_files = list(self.root.glob("**/*.gradle")) + list(
                self.root.glob("**/*.gradle.kts")
            )
            for gf in gradle_files[:10]:  # limit scan
                try:
                    content = gf.read_text(encoding="utf-8", errors="ignore")
                    if "androidx.compose" in content or "compose" in content.lower():
                        frameworks.append("Jetpack Compose")
                        break
                except OSError:
                    pass
        elif project_type == ProjectType.IOS:
            frameworks.append("UIKit/SwiftUI")
            if (self.root / "Podfile").exists():
                frameworks.append("CocoaPods")
            if (self.root / "Package.swift").exists():
                frameworks.append("Swift Package Manager")
        return frameworks

    def _detect_project_name(self) -> str:
        return self.root.name

    def _detect_sub_projects(self) -> list[str]:
        """Detect module/sub-project directories."""
        subs: list[str] = []
        for child in self.root.iterdir():
            if not child.is_dir() or child.name.startswith("."):
                continue
            if (child / "build.gradle").exists() or (
                child / "build.gradle.kts"
            ).exists():
                subs.append(child.name)
        return subs

    # ------------------------------------------------------------------
    # Android v1.1: CLI + Skills detection
    # ------------------------------------------------------------------

    def _detect_android_cli(self) -> bool:
        """Check if Android CLI is available. Returns False immediately when disabled."""
        if not self._android_cli_enabled:
            return False
        if shutil.which("android"):
            return True
        kote_android = Path.home() / ".kote" / "bin" / "android"
        return kote_android.exists()

    def _scan_for_skills(self) -> list[str]:
        """Scan for SKILL.md files and build.gradle keywords."""
        found: list[str] = []

        # Look for SKILL.md files
        for skill_file in self.root.glob("**/SKILL.md"):
            try:
                content = skill_file.read_text(encoding="utf-8", errors="ignore")
                # Extract skill name from H1 header
                m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
                if m:
                    found.append(m.group(1).strip())
            except OSError:
                pass

        # Check build.gradle files for known skill keywords
        gradle_files = list(self.root.glob("**/*.gradle")) + list(
            self.root.glob("**/*.gradle.kts")
        )
        for gf in gradle_files[:20]:
            try:
                content = gf.read_text(encoding="utf-8", errors="ignore")
                for skill_name, keywords in _SKILL_KEYWORDS.items():
                    if skill_name not in found:
                        if any(kw.lower() in content.lower() for kw in keywords):
                            found.append(skill_name)
            except OSError:
                pass

        return list(dict.fromkeys(found))

    def _scan_agent_keywords(self) -> list[str]:
        """Scan README.md and ARCHITECTURE.md for agent-related keywords."""
        found: list[str] = []
        for doc_name in ("README.md", "ARCHITECTURE.md"):
            doc_path = self.root / doc_name
            if doc_path.exists():
                try:
                    content = doc_path.read_text(encoding="utf-8", errors="ignore").lower()
                    for kw in _AGENT_KEYWORDS:
                        if kw in content and kw not in found:
                            found.append(kw)
                except OSError:
                    pass
        return found

    def _suggest_skills(self, info: ProjectInfo) -> list[str]:
        """Map detected features to recommended skill names."""
        suggestions: list[str] = []
        if info.project_type not in (ProjectType.ANDROID, ProjectType.MONOREPO):
            return suggestions

        # Check frameworks
        if "Jetpack Compose" in info.frameworks:
            if "compose-migration" not in info.detected_skills:
                suggestions.append("compose-migration")

        # Check for navigation usage in gradle
        gradle_files = list(self.root.glob("**/*.gradle")) + list(
            self.root.glob("**/*.gradle.kts")
        )
        for gf in gradle_files[:10]:
            try:
                content = gf.read_text(encoding="utf-8", errors="ignore")
                if "navigation" in content.lower():
                    if "navigation3" not in info.detected_skills:
                        suggestions.append("navigation3")
                    break
            except OSError:
                pass

        return suggestions

    # ------------------------------------------------------------------
    # Documentation analysis
    # ------------------------------------------------------------------

    def _analyze_documentation(self) -> dict[str, list[str]]:
        """
        Scan README, ARCHITECTURE, CONTRIBUTING, docs/**, .github/**/*.md
        and extract headers + score keywords.
        """
        doc_summary: dict[str, list[str]] = {}
        arch_keywords = [
            "mvvm",
            "clean",
            "architecture",
            "compose",
            "swiftui",
            "coordinator",
            "viper",
            "redux",
            "mvi",
            "repository",
            "usecase",
            "viewmodel",
        ]

        # Collect documentation files
        doc_files: list[Path] = []
        for name in ("README.md", "ARCHITECTURE.md", "CONTRIBUTING.md"):
            p = self.root / name
            if p.exists():
                doc_files.append(p)

        # docs/** and .github/**/*.md
        for pattern in ("docs/**/*.md", ".github/**/*.md"):
            doc_files.extend(self.root.glob(pattern))

        for doc_path in doc_files:
            try:
                content = doc_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            headers: list[str] = []
            for line in content.splitlines():
                m = re.match(r"^#{1,2}\s+(.+)$", line)
                if m:
                    headers.append(m.group(1).strip())

            # Score keywords
            content_lower = content.lower()
            found_kw = [kw for kw in arch_keywords if kw in content_lower]
            if found_kw:
                headers.extend([f"[keyword:{kw}]" for kw in found_kw])

            rel_name = str(doc_path.relative_to(self.root))
            doc_summary[rel_name] = headers

        return doc_summary

    # ------------------------------------------------------------------
    # Enrichment
    # ------------------------------------------------------------------

    def _enrich_android(self, info: ProjectInfo) -> ProjectInfo:
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
