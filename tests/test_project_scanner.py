"""Comprehensive tests for koteguard/project_scanner.py.

Uses synthetic temporary project structures to exercise every detector and scanner method
without needing real Android/iOS SDKs.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from koteguard.models import ProjectInfo, ProjectType
from koteguard.project_scanner import (
    ProjectScanner,
    _find_files,
    _has_extension_dir,
    _has_file,
    _parse_build_gradle,
    _parse_info_plist,
)

# ---------------------------------------------------------------------------
# Filesystem helper utilities
# ---------------------------------------------------------------------------


class TestFindFiles:
    def test_finds_file_at_root(self, tmp_path):
        (tmp_path / "build.gradle").touch()
        results = _find_files(tmp_path, "build.gradle")
        assert any(p.name == "build.gradle" for p in results)

    def test_finds_nested_file(self, tmp_path):
        nested = tmp_path / "app"
        nested.mkdir()
        (nested / "build.gradle").touch()
        results = _find_files(tmp_path, "build.gradle")
        assert len(results) > 0

    def test_respects_max_depth(self, tmp_path):
        deep = tmp_path / "a" / "b" / "c" / "d" / "e" / "f"
        deep.mkdir(parents=True)
        (deep / "build.gradle").touch()
        results = _find_files(tmp_path, "build.gradle", max_depth=2)
        assert not any("d/e/f" in str(p) or "c/d" in str(p) for p in results)

    def test_no_duplicates(self, tmp_path):
        (tmp_path / "build.gradle").touch()
        results = _find_files(tmp_path, "build.gradle")
        assert len(results) == len(set(str(p) for p in results))


class TestHasFile:
    def test_true_when_file_exists(self, tmp_path):
        (tmp_path / "gradlew").touch()
        assert _has_file(tmp_path, "gradlew") is True

    def test_false_when_file_missing(self, tmp_path):
        assert _has_file(tmp_path, "nonexistent.gradle") is False


class TestHasExtensionDir:
    def test_true_when_xcodeproj_exists(self, tmp_path):
        (tmp_path / "MyApp.xcodeproj").mkdir()
        assert _has_extension_dir(tmp_path, ".xcodeproj") is True

    def test_false_when_not_found(self, tmp_path):
        assert _has_extension_dir(tmp_path, ".xcodeproj") is False


# ---------------------------------------------------------------------------
# _parse_build_gradle
# ---------------------------------------------------------------------------


class TestParseBuildGradle:
    def test_extracts_application_id(self, tmp_path):
        gradle = tmp_path / "build.gradle"
        gradle.write_text('applicationId "com.example.myapp"\n', encoding="utf-8")
        data = _parse_build_gradle(gradle)
        assert data["android_package"] == "com.example.myapp"

    def test_extracts_min_sdk(self, tmp_path):
        gradle = tmp_path / "build.gradle"
        gradle.write_text("minSdk 26\n", encoding="utf-8")
        data = _parse_build_gradle(gradle)
        assert data["android_min_sdk"] == 26

    def test_extracts_min_sdk_version(self, tmp_path):
        gradle = tmp_path / "build.gradle"
        gradle.write_text("minSdkVersion 21\n", encoding="utf-8")
        data = _parse_build_gradle(gradle)
        assert data["android_min_sdk"] == 21

    def test_extracts_target_sdk(self, tmp_path):
        gradle = tmp_path / "build.gradle"
        gradle.write_text("targetSdk 34\n", encoding="utf-8")
        data = _parse_build_gradle(gradle)
        assert data["android_target_sdk"] == 34

    def test_extracts_compile_sdk(self, tmp_path):
        gradle = tmp_path / "build.gradle"
        gradle.write_text("compileSdk 34\n", encoding="utf-8")
        data = _parse_build_gradle(gradle)
        assert data["android_compile_sdk"] == 34

    def test_extracts_all_fields(self, tmp_path):
        gradle = tmp_path / "build.gradle"
        content = """
android {
    compileSdk 34
    defaultConfig {
        applicationId "com.example.app"
        minSdk 26
        targetSdk 34
    }
}
"""
        gradle.write_text(content, encoding="utf-8")
        data = _parse_build_gradle(gradle)
        assert data["android_package"] == "com.example.app"
        assert data["android_min_sdk"] == 26
        assert data["android_target_sdk"] == 34
        assert data["android_compile_sdk"] == 34

    def test_returns_empty_for_missing_file(self, tmp_path):
        data = _parse_build_gradle(tmp_path / "nonexistent.gradle")
        assert data == {}

    def test_returns_empty_for_unrelated_content(self, tmp_path):
        gradle = tmp_path / "build.gradle"
        gradle.write_text("// No android config here\n", encoding="utf-8")
        data = _parse_build_gradle(gradle)
        assert data == {}

    def test_single_quoted_application_id(self, tmp_path):
        gradle = tmp_path / "build.gradle"
        gradle.write_text("applicationId 'com.example.single'\n", encoding="utf-8")
        data = _parse_build_gradle(gradle)
        assert data["android_package"] == "com.example.single"


# ---------------------------------------------------------------------------
# _parse_info_plist
# ---------------------------------------------------------------------------


class TestParseInfoPlist:
    def test_extracts_bundle_id(self, tmp_path):
        plist_data = {
            "CFBundleIdentifier": "com.example.ios",
            "MinimumOSVersion": "16.0",
        }
        plist_path = tmp_path / "Info.plist"
        with plist_path.open("wb") as f:
            plistlib.dump(plist_data, f)

        data = _parse_info_plist(plist_path)
        assert data["ios_bundle_id"] == "com.example.ios"
        assert data["ios_deployment_target"] == "16.0"

    def test_returns_empty_for_missing_file(self, tmp_path):
        data = _parse_info_plist(tmp_path / "nonexistent.plist")
        assert data == {}

    def test_returns_empty_for_invalid_plist(self, tmp_path):
        bad_plist = tmp_path / "Info.plist"
        bad_plist.write_text("NOT A PLIST", encoding="utf-8")
        data = _parse_info_plist(bad_plist)
        assert data == {}

    def test_handles_missing_minimum_os_version(self, tmp_path):
        plist_data = {"CFBundleIdentifier": "com.example.app"}
        plist_path = tmp_path / "Info.plist"
        with plist_path.open("wb") as f:
            plistlib.dump(plist_data, f)

        data = _parse_info_plist(plist_path)
        assert data["ios_bundle_id"] == "com.example.app"
        assert data.get("ios_deployment_target") is None


# ---------------------------------------------------------------------------
# ProjectScanner – project type detection
# ---------------------------------------------------------------------------


def _make_android_project(root: Path) -> None:
    (root / "build.gradle").write_text('id "com.android.application"\n', encoding="utf-8")
    (root / "settings.gradle").write_text('include ":app"\n', encoding="utf-8")
    (root / "gradlew").touch()


def _make_ios_project(root: Path) -> None:
    (root / "MyApp.xcodeproj").mkdir()


class TestProjectScannerDetection:
    def test_detects_android_project(self, tmp_path):
        _make_android_project(tmp_path)
        scanner = ProjectScanner(tmp_path)
        info = scanner.scan()
        assert info.project_type == ProjectType.ANDROID
        assert info.confidence >= 0.9

    def test_detects_ios_project(self, tmp_path):
        _make_ios_project(tmp_path)
        scanner = ProjectScanner(tmp_path)
        info = scanner.scan()
        assert info.project_type == ProjectType.IOS
        assert info.confidence >= 0.9

    def test_detects_monorepo(self, tmp_path):
        _make_android_project(tmp_path)
        _make_ios_project(tmp_path)
        scanner = ProjectScanner(tmp_path)
        info = scanner.scan()
        # Either MONOREPO or ANDROID/IOS — both are valid detections
        assert info.project_type in (ProjectType.MONOREPO, ProjectType.ANDROID, ProjectType.IOS)

    def test_unknown_project_returns_unknown(self, tmp_path):
        scanner = ProjectScanner(tmp_path)
        info = scanner.scan()
        assert info.project_type == ProjectType.UNKNOWN
        assert info.confidence == 0.0

    def test_project_name_is_directory_name(self, tmp_path):
        scanner = ProjectScanner(tmp_path)
        info = scanner.scan()
        assert info.project_name == tmp_path.name

    def test_elapsed_ms_is_positive(self, tmp_path):
        scanner = ProjectScanner(tmp_path)
        info = scanner.scan()
        assert info.elapsed_ms >= 0.0


# ---------------------------------------------------------------------------
# ProjectScanner – has_tests, has_ci
# ---------------------------------------------------------------------------


class TestProjectScannerFlags:
    def test_has_tests_true_with_test_dir(self, tmp_path):
        (tmp_path / "tests").mkdir()
        scanner = ProjectScanner(tmp_path)
        assert scanner._has_tests() is True

    def test_has_tests_true_with_android_test_dir(self, tmp_path):
        (tmp_path / "app" / "src" / "androidTest").mkdir(parents=True)
        scanner = ProjectScanner(tmp_path)
        assert scanner._has_tests() is True

    def test_has_tests_false_when_no_test_dir(self, tmp_path):
        scanner = ProjectScanner(tmp_path)
        assert scanner._has_tests() is False

    def test_has_ci_true_with_github_workflows(self, tmp_path):
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        scanner = ProjectScanner(tmp_path)
        assert scanner._has_ci() is True

    def test_has_ci_true_with_circleci(self, tmp_path):
        (tmp_path / ".circleci").mkdir()
        scanner = ProjectScanner(tmp_path)
        assert scanner._has_ci() is True

    def test_has_ci_true_with_travis_yml(self, tmp_path):
        (tmp_path / ".travis.yml").touch()
        scanner = ProjectScanner(tmp_path)
        assert scanner._has_ci() is True

    def test_has_ci_true_with_fastfile(self, tmp_path):
        (tmp_path / "Fastfile").touch()
        scanner = ProjectScanner(tmp_path)
        assert scanner._has_ci() is True

    def test_has_ci_false_when_no_ci(self, tmp_path):
        scanner = ProjectScanner(tmp_path)
        assert scanner._has_ci() is False


# ---------------------------------------------------------------------------
# ProjectScanner – detect_languages
# ---------------------------------------------------------------------------


class TestDetectLanguages:
    def test_detects_kotlin(self, tmp_path):
        (tmp_path / "Main.kt").touch()
        scanner = ProjectScanner(tmp_path)
        langs = scanner._detect_languages()
        assert "Kotlin" in langs

    def test_detects_swift(self, tmp_path):
        (tmp_path / "App.swift").touch()
        scanner = ProjectScanner(tmp_path)
        langs = scanner._detect_languages()
        assert "Swift" in langs

    def test_detects_java(self, tmp_path):
        (tmp_path / "Main.java").touch()
        scanner = ProjectScanner(tmp_path)
        langs = scanner._detect_languages()
        assert "Java" in langs

    def test_detects_python(self, tmp_path):
        (tmp_path / "script.py").touch()
        scanner = ProjectScanner(tmp_path)
        langs = scanner._detect_languages()
        assert "Python" in langs

    def test_skips_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "index.js").touch()
        scanner = ProjectScanner(tmp_path)
        langs = scanner._detect_languages()
        assert "JavaScript" not in langs

    def test_returns_sorted_list(self, tmp_path):
        (tmp_path / "Main.kt").touch()
        (tmp_path / "App.swift").touch()
        scanner = ProjectScanner(tmp_path)
        langs = scanner._detect_languages()
        assert langs == sorted(langs)


# ---------------------------------------------------------------------------
# ProjectScanner – detect_frameworks
# ---------------------------------------------------------------------------


class TestDetectFrameworks:
    def test_android_always_includes_android_sdk(self, tmp_path):
        scanner = ProjectScanner(tmp_path)
        frameworks = scanner._detect_frameworks(ProjectType.ANDROID)
        assert "Android SDK" in frameworks

    def test_android_includes_gradle_if_present(self, tmp_path):
        (tmp_path / "build.gradle").touch()
        scanner = ProjectScanner(tmp_path)
        frameworks = scanner._detect_frameworks(ProjectType.ANDROID)
        assert "Gradle" in frameworks

    def test_android_detects_compose(self, tmp_path):
        (tmp_path / "build.gradle").write_text(
            "androidx.compose.bom:2024.01.00\n", encoding="utf-8"
        )
        scanner = ProjectScanner(tmp_path)
        frameworks = scanner._detect_frameworks(ProjectType.ANDROID)
        assert "Jetpack Compose" in frameworks

    def test_ios_includes_uikit_swiftui(self, tmp_path):
        scanner = ProjectScanner(tmp_path)
        frameworks = scanner._detect_frameworks(ProjectType.IOS)
        assert "UIKit/SwiftUI" in frameworks

    def test_ios_detects_cocoapods(self, tmp_path):
        (tmp_path / "Podfile").touch()
        scanner = ProjectScanner(tmp_path)
        frameworks = scanner._detect_frameworks(ProjectType.IOS)
        assert "CocoaPods" in frameworks

    def test_ios_detects_spm(self, tmp_path):
        (tmp_path / "Package.swift").touch()
        scanner = ProjectScanner(tmp_path)
        frameworks = scanner._detect_frameworks(ProjectType.IOS)
        assert "Swift Package Manager" in frameworks

    def test_unknown_returns_empty(self, tmp_path):
        scanner = ProjectScanner(tmp_path)
        frameworks = scanner._detect_frameworks(ProjectType.UNKNOWN)
        assert frameworks == []


# ---------------------------------------------------------------------------
# ProjectScanner – detect_sub_projects
# ---------------------------------------------------------------------------


class TestDetectSubProjects:
    def test_finds_sub_project_with_gradle(self, tmp_path):
        submodule = tmp_path / "feature-module"
        submodule.mkdir()
        (submodule / "build.gradle").touch()
        scanner = ProjectScanner(tmp_path)
        subs = scanner._detect_sub_projects()
        assert "feature-module" in subs

    def test_skips_hidden_directories(self, tmp_path):
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "build.gradle").touch()
        scanner = ProjectScanner(tmp_path)
        subs = scanner._detect_sub_projects()
        assert ".hidden" not in subs

    def test_skips_non_gradle_dirs(self, tmp_path):
        regular = tmp_path / "regular-dir"
        regular.mkdir()
        scanner = ProjectScanner(tmp_path)
        subs = scanner._detect_sub_projects()
        assert "regular-dir" not in subs


# ---------------------------------------------------------------------------
# ProjectScanner – detect_android_cli
# ---------------------------------------------------------------------------


class TestDetectAndroidCli:
    def test_returns_false_when_disabled(self, tmp_path):
        scanner = ProjectScanner(tmp_path, android_cli_enabled=False)
        assert scanner._detect_android_cli() is False

    def test_returns_true_when_android_in_path(self, tmp_path):
        import shutil
        from unittest.mock import patch

        scanner = ProjectScanner(tmp_path, android_cli_enabled=True)
        with patch("koteguard.project_scanner.shutil.which", return_value="/usr/bin/android"):
            result = scanner._detect_android_cli()
        assert result is True

    def test_returns_false_when_not_in_path_and_no_kote_bin(self, tmp_path):
        from unittest.mock import patch

        scanner = ProjectScanner(tmp_path, android_cli_enabled=True)
        with (
            patch("koteguard.project_scanner.shutil.which", return_value=None),
            patch("koteguard.project_scanner.Path.home", return_value=tmp_path),
        ):
            result = scanner._detect_android_cli()
        assert result is False

    def test_finds_kote_android_binary(self, tmp_path):
        from unittest.mock import patch

        kote_bin = tmp_path / ".kote" / "bin"
        kote_bin.mkdir(parents=True)
        android_bin = kote_bin / "android"
        android_bin.touch()

        scanner = ProjectScanner(tmp_path, android_cli_enabled=True)
        with (
            patch("koteguard.project_scanner.shutil.which", return_value=None),
            patch("koteguard.project_scanner.Path.home", return_value=tmp_path),
        ):
            result = scanner._detect_android_cli()
        assert result is True


# ---------------------------------------------------------------------------
# ProjectScanner – scan_for_skills
# ---------------------------------------------------------------------------


class TestScanForSkills:
    def test_finds_navigation3_keyword(self, tmp_path):
        gradle = tmp_path / "build.gradle"
        gradle.write_text(
            "implementation 'androidx.navigation:navigation-compose:2.7.0'\n", encoding="utf-8"
        )
        scanner = ProjectScanner(tmp_path)
        skills = scanner._scan_for_skills()
        assert "navigation3" in skills

    def test_finds_edge_to_edge_keyword(self, tmp_path):
        gradle = tmp_path / "build.gradle"
        gradle.write_text(
            "WindowCompat.setDecorFitsSystemWindows(window, false)\n", encoding="utf-8"
        )
        scanner = ProjectScanner(tmp_path)
        skills = scanner._scan_for_skills()
        assert "edge-to-edge" in skills

    def test_finds_compose_migration_keyword(self, tmp_path):
        gradle = tmp_path / "build.gradle"
        gradle.write_text("implementation 'androidx.compose.ui:ui:1.6.0'\n", encoding="utf-8")
        scanner = ProjectScanner(tmp_path)
        skills = scanner._scan_for_skills()
        assert "compose-migration" in skills

    def test_finds_skill_from_skill_md(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("# navigation3\n\nBest practices.\n", encoding="utf-8")
        scanner = ProjectScanner(tmp_path)
        skills = scanner._scan_for_skills()
        assert "navigation3" in skills

    def test_no_duplicates(self, tmp_path):
        gradle = tmp_path / "build.gradle"
        gradle.write_text("androidx.navigation:navigation-compose\n", encoding="utf-8")
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("# navigation3\n\nDesc.\n", encoding="utf-8")
        scanner = ProjectScanner(tmp_path)
        skills = scanner._scan_for_skills()
        assert skills.count("navigation3") == 1

    def test_empty_project_returns_no_skills(self, tmp_path):
        scanner = ProjectScanner(tmp_path)
        skills = scanner._scan_for_skills()
        assert skills == []


# ---------------------------------------------------------------------------
# ProjectScanner – scan_for_ios_skills
# ---------------------------------------------------------------------------


class TestScanForIosSkills:
    def test_detects_swiftui_patterns(self, tmp_path):
        swift_file = tmp_path / "ContentView.swift"
        swift_file.write_text(
            "import SwiftUI\n\nstruct ContentView: some View {\n}\n", encoding="utf-8"
        )
        scanner = ProjectScanner(tmp_path)
        skills = scanner._scan_for_ios_skills()
        assert "swiftui-patterns" in skills

    def test_detects_swift_concurrency(self, tmp_path):
        swift_file = tmp_path / "Service.swift"
        swift_file.write_text(
            "func fetchData() async throws -> Data {\n  let result = await api()\n}\n",
            encoding="utf-8",
        )
        scanner = ProjectScanner(tmp_path)
        skills = scanner._scan_for_ios_skills()
        assert "swift-concurrency" in skills

    def test_detects_xctest(self, tmp_path):
        test_file = tmp_path / "MyTests.swift"
        test_file.write_text("import XCTest\n\nclass MyTests: XCTestCase {\n}\n", encoding="utf-8")
        scanner = ProjectScanner(tmp_path)
        skills = scanner._scan_for_ios_skills()
        assert "xctest" in skills

    def test_detects_xctest_from_package_swift(self, tmp_path):
        pkg_swift = tmp_path / "Package.swift"
        pkg_swift.write_text(
            '.package(url: "https://github.com/pointfreeco/swift-snapshot-testing", from: "1.15.0"),\n',
            encoding="utf-8",
        )
        pkg_swift.write_text("SnapshotTesting dependency here\n", encoding="utf-8")
        scanner = ProjectScanner(tmp_path)
        skills = scanner._scan_for_ios_skills()
        assert "xctest" in skills

    def test_no_swift_files_returns_empty(self, tmp_path):
        scanner = ProjectScanner(tmp_path)
        skills = scanner._scan_for_ios_skills()
        assert skills == []


# ---------------------------------------------------------------------------
# ProjectScanner – scan_agent_keywords
# ---------------------------------------------------------------------------


class TestScanAgentKeywords:
    def test_finds_copilot_in_readme(self, tmp_path):
        readme = tmp_path / "README.md"
        readme.write_text(
            "# Project\n\nThis project uses copilot for AI assistance.\n", encoding="utf-8"
        )
        scanner = ProjectScanner(tmp_path)
        keywords = scanner._scan_agent_keywords()
        assert "copilot" in keywords

    def test_finds_agent_keyword(self, tmp_path):
        arch = tmp_path / "ARCHITECTURE.md"
        arch.write_text("# Architecture\n\nAI agent workflows.\n", encoding="utf-8")
        scanner = ProjectScanner(tmp_path)
        keywords = scanner._scan_agent_keywords()
        assert "agent" in keywords

    def test_empty_when_no_docs(self, tmp_path):
        scanner = ProjectScanner(tmp_path)
        keywords = scanner._scan_agent_keywords()
        assert keywords == []


# ---------------------------------------------------------------------------
# ProjectScanner – suggest_skills
# ---------------------------------------------------------------------------


class TestSuggestSkills:
    def test_suggests_compose_migration_for_compose_framework(self, tmp_path):
        info = ProjectInfo(
            project_type=ProjectType.ANDROID,
            frameworks=["Android SDK", "Jetpack Compose"],
        )
        scanner = ProjectScanner(tmp_path)
        suggestions = scanner._suggest_skills(info)
        assert "compose-migration" in suggestions

    def test_no_duplicate_suggestion(self, tmp_path):
        info = ProjectInfo(
            project_type=ProjectType.ANDROID,
            frameworks=["Jetpack Compose"],
            detected_skills=["compose-migration"],
        )
        scanner = ProjectScanner(tmp_path)
        suggestions = scanner._suggest_skills(info)
        assert "compose-migration" not in suggestions

    def test_no_suggestions_for_ios(self, tmp_path):
        info = ProjectInfo(project_type=ProjectType.IOS)
        scanner = ProjectScanner(tmp_path)
        suggestions = scanner._suggest_skills(info)
        assert suggestions == []

    def test_suggests_navigation3_from_gradle(self, tmp_path):
        gradle = tmp_path / "build.gradle"
        gradle.write_text("implementation 'navigation-something'\n", encoding="utf-8")
        info = ProjectInfo(project_type=ProjectType.ANDROID)
        scanner = ProjectScanner(tmp_path)
        suggestions = scanner._suggest_skills(info)
        assert "navigation3" in suggestions


# ---------------------------------------------------------------------------
# ProjectScanner – analyze_documentation
# ---------------------------------------------------------------------------


class TestAnalyzeDocumentation:
    def test_extracts_headers_from_readme(self, tmp_path):
        readme = tmp_path / "README.md"
        readme.write_text("# Project\n\n## Installation\n\n## Usage\n\n", encoding="utf-8")
        scanner = ProjectScanner(tmp_path)
        doc_summary = scanner._analyze_documentation()
        assert "README.md" in doc_summary
        assert "Installation" in doc_summary["README.md"]

    def test_detects_architecture_keywords(self, tmp_path):
        readme = tmp_path / "README.md"
        readme.write_text(
            "# App\n\nThis app uses MVVM with clean architecture.\n", encoding="utf-8"
        )
        scanner = ProjectScanner(tmp_path)
        doc_summary = scanner._analyze_documentation()
        keywords = doc_summary.get("README.md", [])
        assert any("[keyword:mvvm]" in k for k in keywords)
        assert any("[keyword:clean]" in k for k in keywords)

    def test_empty_when_no_docs(self, tmp_path):
        scanner = ProjectScanner(tmp_path)
        doc_summary = scanner._analyze_documentation()
        assert doc_summary == {}

    def test_scans_github_md_files(self, tmp_path):
        gh_dir = tmp_path / ".github"
        gh_dir.mkdir()
        contributing = gh_dir / "CONTRIBUTING.md"
        contributing.write_text("# Contributing\n\n## Guidelines\n\n", encoding="utf-8")
        scanner = ProjectScanner(tmp_path)
        doc_summary = scanner._analyze_documentation()
        assert any(".github" in key for key in doc_summary)


# ---------------------------------------------------------------------------
# ProjectScanner – enrich_android / enrich_ios
# ---------------------------------------------------------------------------


class TestEnrichAndroid:
    def test_extracts_package_from_build_gradle(self, tmp_path):
        gradle = tmp_path / "build.gradle"
        gradle.write_text('applicationId "com.example.myapp"\nminSdk 28\n', encoding="utf-8")
        info = ProjectInfo(project_type=ProjectType.ANDROID)
        scanner = ProjectScanner(tmp_path)
        enriched = scanner._enrich_android(info)
        assert enriched.android_package == "com.example.myapp"
        assert enriched.android_min_sdk == 28

    def test_returns_info_unchanged_when_no_gradle(self, tmp_path):
        info = ProjectInfo(project_type=ProjectType.ANDROID)
        scanner = ProjectScanner(tmp_path)
        enriched = scanner._enrich_android(info)
        assert enriched.android_package is None


class TestEnrichIos:
    def test_extracts_bundle_id_from_plist(self, tmp_path):
        plist_data = {
            "CFBundleIdentifier": "com.example.ios",
            "MinimumOSVersion": "17.0",
        }
        plist_path = tmp_path / "Info.plist"
        with plist_path.open("wb") as f:
            plistlib.dump(plist_data, f)

        info = ProjectInfo(project_type=ProjectType.IOS)
        scanner = ProjectScanner(tmp_path)
        enriched = scanner._enrich_ios(info)
        assert enriched.ios_bundle_id == "com.example.ios"
        assert enriched.ios_deployment_target == "17.0"

    def test_returns_info_unchanged_when_no_plist(self, tmp_path):
        info = ProjectInfo(project_type=ProjectType.IOS)
        scanner = ProjectScanner(tmp_path)
        enriched = scanner._enrich_ios(info)
        assert enriched.ios_bundle_id is None


# ---------------------------------------------------------------------------
# ProjectScanner – full scan integration
# ---------------------------------------------------------------------------


class TestFullScanIntegration:
    def test_android_scan_populates_all_fields(self, tmp_path):
        _make_android_project(tmp_path)
        (tmp_path / "app" / "build.gradle").parent.mkdir(exist_ok=True)
        (tmp_path / "app" / "build.gradle").write_text(
            'applicationId "com.example.full"\nminSdk 26\ntargetSdk 34\ncompileSdk 34\n',
            encoding="utf-8",
        )
        (tmp_path / "tests").mkdir()
        (tmp_path / ".github" / "workflows").mkdir(parents=True)

        scanner = ProjectScanner(tmp_path)
        info = scanner.scan()

        assert info.project_type == ProjectType.ANDROID
        assert info.has_tests is True
        assert info.has_ci is True
        assert info.android_package == "com.example.full"
        assert info.android_min_sdk == 26
        assert info.elapsed_ms >= 0

    def test_ios_scan_populates_all_fields(self, tmp_path):
        _make_ios_project(tmp_path)
        (tmp_path / "App.swift").write_text("import SwiftUI\n", encoding="utf-8")

        scanner = ProjectScanner(tmp_path)
        info = scanner.scan()

        assert info.project_type == ProjectType.IOS
        assert "Swift" in info.languages
        assert "swiftui-patterns" in info.ios_detected_skills

    def test_scan_result_is_project_info(self, tmp_path):
        scanner = ProjectScanner(tmp_path)
        info = scanner.scan()
        assert isinstance(info, ProjectInfo)
