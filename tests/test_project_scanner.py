"""Tests for the project scanner (Phase 0)."""

from __future__ import annotations

from pathlib import Path

import pytest

from koteguard.models import ProjectType
from koteguard.project_scanner import (
    ProjectScanner,
    _parse_build_gradle,
    _parse_info_plist,
    _parse_pubspec,
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
    compileSdkVersion 34
    defaultConfig {
        applicationId "com.example.myapp"
        minSdkVersion 21
        targetSdkVersion 34
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
            'applicationId "com.test.app"\nminSdkVersion 24\ntargetSdkVersion 33\ncompileSdkVersion 33\n',
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


# ---------------------------------------------------------------------------
# Flutter project
# ---------------------------------------------------------------------------


class TestFlutterProject:
    def test_detects_flutter(self, tmp_path):
        _write(
            tmp_path / "pubspec.yaml",
            "name: my_flutter_app\nflutter:\n  sdk: flutter\n",
        )
        scanner = ProjectScanner(tmp_path)
        info = scanner.scan()
        assert info.project_type == ProjectType.FLUTTER
        assert info.confidence >= 0.9

    def test_flutter_project_name(self, tmp_path):
        _write(
            tmp_path / "pubspec.yaml",
            "name: cool_app\ndescription: A Flutter app\n",
        )
        scanner = ProjectScanner(tmp_path)
        info = scanner.scan()
        assert info.project_name == "cool_app"


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


# ---------------------------------------------------------------------------
# parse_pubspec
# ---------------------------------------------------------------------------


class TestParsePubspec:
    def test_parses_name(self, tmp_path):
        f = _write(tmp_path / "pubspec.yaml", "name: my_app\n")
        result = _parse_pubspec(f)
        assert result["project_name"] == "my_app"

    def test_missing_file(self, tmp_path):
        result = _parse_pubspec(tmp_path / "missing.yaml")
        assert result == {}
