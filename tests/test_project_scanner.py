"""Tests for the project scanner (Phase 0) – Android + iOS only."""

from __future__ import annotations

from pathlib import Path

import pytest

from koteguard.models import ProjectType
from koteguard.project_scanner import (
    ProjectScanner,
    _parse_build_gradle,
    _parse_info_plist,
)


# ---------------------------------------------------------------------------
# Helpers to build fake project trees
# ---------------------------------------------------------------------------


def _write(path: Path, content: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Android project
# ---------------------------------------------------------------------------


class TestAndroidProject:
    def test_detects_android(self, tmp_path):
        _write(tmp_path / "build.gradle", "// root gradle")
        _write(
            tmp_path / "app" / "build.gradle",
            """
android {
    compileSdk 34
    defaultConfig {
        applicationId "com.example.myapp"
        minSdk 21
        targetSdk 34
    }
}
""",
        )
        _write(tmp_path / "gradlew", "")
        scanner = ProjectScanner(tmp_path)
        info = scanner.scan()
        assert info.project_type == ProjectType.ANDROID
        assert info.confidence >= 0.8

    def test_android_enrichment(self, tmp_path):
        _write(
            tmp_path / "app" / "build.gradle",
            'applicationId "com.test.app"\nminSdk 24\ntargetSdk 33\ncompileSdk 33\n',
        )
        _write(tmp_path / "build.gradle", "")
        scanner = ProjectScanner(tmp_path)
        info = scanner.scan()
        assert info.android_package == "com.test.app"
        assert info.android_min_sdk == 24
        assert info.android_target_sdk == 33

    def test_has_tests_detected(self, tmp_path):
        _write(tmp_path / "build.gradle", "")
        (tmp_path / "app" / "src" / "androidTest").mkdir(parents=True)
        scanner = ProjectScanner(tmp_path)
        info = scanner.scan()
        assert info.has_tests is True

    def test_has_ci_detected(self, tmp_path):
        _write(tmp_path / "build.gradle", "")
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        _write(tmp_path / ".github" / "workflows" / "ci.yml", "")
        scanner = ProjectScanner(tmp_path)
        info = scanner.scan()
        assert info.has_ci is True

    def test_no_flutter_detected(self, tmp_path):
        """Flutter pubspec.yaml should NOT cause FLUTTER type – that type is removed."""
        _write(tmp_path / "pubspec.yaml", "name: my_flutter_app\n")
        scanner = ProjectScanner(tmp_path)
        info = scanner.scan()
        # Should be UNKNOWN (not FLUTTER)
        assert info.project_type == ProjectType.UNKNOWN

    def test_skill_detection_from_gradle(self, tmp_path):
        _write(tmp_path / "build.gradle", "")
        _write(
            tmp_path / "app" / "build.gradle",
            "implementation 'androidx.navigation:navigation-compose:2.8.0'\n"
            "implementation 'androidx.compose.ui:ui:1.7.0'\n",
        )
        scanner = ProjectScanner(tmp_path)
        skills = scanner._scan_for_skills()
        # "androidx.navigation" keyword matches navigation3; "androidx.compose" matches compose-migration
        assert "navigation3" in skills
        assert "compose-migration" in skills


# ---------------------------------------------------------------------------
# iOS project
# ---------------------------------------------------------------------------


class TestIOSProject:
    def test_detects_ios(self, tmp_path):
        xcodeproj = tmp_path / "MyApp.xcodeproj"
        xcodeproj.mkdir()
        _write(xcodeproj / "project.pbxproj", "")
        scanner = ProjectScanner(tmp_path)
        info = scanner.scan()
        assert info.project_type == ProjectType.IOS
        assert info.confidence >= 0.8

    def test_ios_enrichment_from_plist(self, tmp_path):
        xcodeproj = tmp_path / "App.xcodeproj"
        xcodeproj.mkdir()
        import plistlib

        plist_data = {
            "CFBundleIdentifier": "com.example.iosapp",
            "MinimumOSVersion": "15.0",
        }
        plist_path = tmp_path / "App" / "Info.plist"
        plist_path.parent.mkdir(parents=True)
        with plist_path.open("wb") as fh:
            plistlib.dump(plist_data, fh)

        scanner = ProjectScanner(tmp_path)
        info = scanner.scan()
        assert info.ios_bundle_id == "com.example.iosapp"
        assert info.ios_deployment_target == "15.0"

    def test_no_flutter_field(self, tmp_path):
        """ProjectInfo should not have flutter_sdk field."""
        xcodeproj = tmp_path / "MyApp.xcodeproj"
        xcodeproj.mkdir()
        scanner = ProjectScanner(tmp_path)
        info = scanner.scan()
        assert not hasattr(info, "flutter_sdk")


# ---------------------------------------------------------------------------
# Unknown project
# ---------------------------------------------------------------------------


class TestUnknownProject:
    def test_unknown(self, tmp_path):
        _write(tmp_path / "README.md", "# hello")
        scanner = ProjectScanner(tmp_path)
        info = scanner.scan()
        assert info.project_type == ProjectType.UNKNOWN
        assert info.confidence == 0.0


# ---------------------------------------------------------------------------
# Documentation analysis
# ---------------------------------------------------------------------------


class TestDocAnalysis:
    def test_readme_headers_extracted(self, tmp_path):
        _write(
            tmp_path / "README.md",
            "# My App\n\n## Architecture\n\nMVVM with Clean Architecture\n\n## Setup\n\nRun `./gradlew build`\n",
        )
        scanner = ProjectScanner(tmp_path)
        doc_summary = scanner._analyze_documentation()
        assert "README.md" in doc_summary
        headers = doc_summary["README.md"]
        assert any("Architecture" in h for h in headers)

    def test_architecture_keywords_detected(self, tmp_path):
        _write(
            tmp_path / "ARCHITECTURE.md",
            "# Architecture\n\nThis project uses MVVM with Clean architecture and Compose.\n",
        )
        scanner = ProjectScanner(tmp_path)
        doc_summary = scanner._analyze_documentation()
        assert "ARCHITECTURE.md" in doc_summary
        headers = doc_summary["ARCHITECTURE.md"]
        kw_entries = [h for h in headers if h.startswith("[keyword:")]
        assert any("mvvm" in kw or "clean" in kw or "compose" in kw for kw in kw_entries)

    def test_missing_docs_returns_empty(self, tmp_path):
        scanner = ProjectScanner(tmp_path)
        doc_summary = scanner._analyze_documentation()
        assert isinstance(doc_summary, dict)


# ---------------------------------------------------------------------------
# Android CLI detection
# ---------------------------------------------------------------------------


class TestAndroidCLIDetection:
    def test_no_android_cli(self, tmp_path):
        """In a clean test env with no android binary, should return False."""
        import shutil
        from unittest.mock import patch

        scanner = ProjectScanner(tmp_path)
        # Mock out shutil.which to return None and Path.exists to return False
        with patch("koteguard.project_scanner.shutil.which", return_value=None), \
             patch("pathlib.Path.exists", return_value=False):
            result = scanner._detect_android_cli()
        assert result is False

    def test_android_cli_via_which(self, tmp_path):
        from unittest.mock import patch

        scanner = ProjectScanner(tmp_path)
        with patch("koteguard.project_scanner.shutil.which", return_value="/usr/local/bin/android"):
            result = scanner._detect_android_cli()
        assert result is True


# ---------------------------------------------------------------------------
# Skills suggestion
# ---------------------------------------------------------------------------


class TestSkillsSuggestion:
    def test_suggest_compose_for_compose_project(self, tmp_path):
        _write(tmp_path / "build.gradle", "")
        info_with_compose = __import__("koteguard.models", fromlist=["ProjectInfo"]).ProjectInfo(
            project_type=ProjectType.ANDROID,
            frameworks=["Android SDK", "Jetpack Compose"],
            detected_skills=[],
        )
        scanner = ProjectScanner(tmp_path)
        suggestions = scanner._suggest_skills(info_with_compose)
        assert "compose-migration" in suggestions

    def test_no_suggestions_for_ios(self, tmp_path):
        info_ios = __import__("koteguard.models", fromlist=["ProjectInfo"]).ProjectInfo(
            project_type=ProjectType.IOS,
            frameworks=["UIKit/SwiftUI"],
            detected_skills=[],
        )
        scanner = ProjectScanner(tmp_path)
        suggestions = scanner._suggest_skills(info_ios)
        assert suggestions == []


# ---------------------------------------------------------------------------
# parse_build_gradle
# ---------------------------------------------------------------------------


class TestParseBuildGradle:
    def test_parses_fields(self, tmp_path):
        f = _write(
            tmp_path / "build.gradle",
            'applicationId "com.test.app"\nminSdkVersion 21\ntargetSdkVersion 33\ncompileSdkVersion 34\n',
        )
        result = _parse_build_gradle(f)
        assert result["android_package"] == "com.test.app"
        assert result["android_min_sdk"] == 21
        assert result["android_target_sdk"] == 33
        assert result["android_compile_sdk"] == 34

    def test_empty_file(self, tmp_path):
        f = _write(tmp_path / "build.gradle", "")
        result = _parse_build_gradle(f)
        assert result == {}

    def test_nonexistent_file(self, tmp_path):
        result = _parse_build_gradle(tmp_path / "missing.gradle")
        assert result == {}
