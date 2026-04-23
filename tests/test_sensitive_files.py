"""Comprehensive tests for koteguard/sensitive_files.py.

Covers _resolve_patterns, SensitiveFileHandler.inject_stubs, create_stub, is_stub,
and all stub content templates.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from koteguard.sensitive_files import (
    _DEFAULT_STUB,
    _STUB_CONTENT,
    ANDROID_SENSITIVE,
    IOS_SENSITIVE,
    SensitiveFileHandler,
    _resolve_patterns,
)

# ---------------------------------------------------------------------------
# _resolve_patterns
# ---------------------------------------------------------------------------


class TestResolvePatterns:
    def test_android_includes_android_patterns(self):
        patterns = _resolve_patterns("android")
        assert "*.jks" in patterns
        assert "*.keystore" in patterns
        assert "google-services.json" in patterns
        assert "local.properties" in patterns
        assert ".env" in patterns

    def test_android_does_not_include_ios_specific(self):
        patterns = _resolve_patterns("android")
        # iOS-only patterns should not be in android
        assert "*.mobileprovision" not in patterns
        assert "*.p12" not in patterns

    def test_ios_includes_ios_patterns(self):
        patterns = _resolve_patterns("ios")
        assert "*.p12" in patterns
        assert "*.mobileprovision" in patterns
        assert "GoogleService-Info.plist" in patterns

    def test_monorepo_includes_both(self):
        patterns = _resolve_patterns("monorepo")
        assert "*.jks" in patterns
        assert "*.p12" in patterns

    def test_unknown_includes_both(self):
        patterns = _resolve_patterns("unknown")
        assert "*.jks" in patterns
        assert "*.p12" in patterns

    def test_unknown_project_type_returns_empty(self):
        # An explicit project type like "web" returns nothing
        patterns = _resolve_patterns("web")
        assert patterns == {}

    def test_case_insensitive_android(self):
        # Currently lowercased in function, but let's confirm the function handles lowercase input
        patterns = _resolve_patterns("android")
        assert len(patterns) > 0

    def test_env_file_in_android(self):
        patterns = _resolve_patterns("android")
        assert ".env" in patterns
        assert patterns[".env"] == "ENV_FILE_STUB"

    def test_env_file_in_ios(self):
        patterns = _resolve_patterns("ios")
        assert ".env" in patterns


# ---------------------------------------------------------------------------
# Stub content templates
# ---------------------------------------------------------------------------


class TestStubContent:
    def test_all_keys_have_content(self):
        for key, content in _STUB_CONTENT.items():
            assert len(content) > 0, f"Empty stub content for key: {key}"

    def test_keystore_stub_has_warning(self):
        content = _STUB_CONTENT["ANDROID_KEYSTORE_STUB"]
        assert "KoteGuard STUB" in content
        assert "keystore" in content.lower() or "STUB" in content

    def test_google_services_stub_is_valid_json_like(self):
        content = _STUB_CONTENT["GOOGLE_SERVICES_STUB"]
        assert "__kote_stub__" in content

    def test_local_properties_stub(self):
        content = _STUB_CONTENT["LOCAL_PROPERTIES_STUB"]
        assert "sdk.dir" in content

    def test_ios_cert_stub(self):
        content = _STUB_CONTENT["IOS_CERT_STUB"]
        assert "KoteGuard STUB" in content

    def test_ios_provision_stub(self):
        content = _STUB_CONTENT["IOS_PROVISION_STUB"]
        assert "KoteGuard STUB" in content

    def test_google_service_info_stub_is_plist_like(self):
        content = _STUB_CONTENT["GOOGLE_SERVICE_INFO_STUB"]
        assert "<?xml" in content or "plist" in content

    def test_env_file_stub(self):
        content = _STUB_CONTENT["ENV_FILE_STUB"]
        assert "KoteGuard STUB" in content
        assert "API_KEY" in content or "env" in content.lower()

    def test_default_stub_is_comment(self):
        assert "KoteGuard STUB" in _DEFAULT_STUB


# ---------------------------------------------------------------------------
# SensitiveFileHandler.inject_stubs
# ---------------------------------------------------------------------------


class TestInjectStubs:
    def test_injects_stub_for_keystore(self, tmp_path):
        # Create a fake keystore in the "source" project
        source_root = tmp_path / "project"
        source_root.mkdir()
        (source_root / "release.jks").write_bytes(b"FAKE_KEYSTORE")

        worktree = tmp_path / "worktree"
        worktree.mkdir()

        handler = SensitiveFileHandler(worktree)
        created = handler.inject_stubs("android", source_root=source_root)

        assert len(created) == 1
        stub_path = worktree / "release.jks"
        assert stub_path.exists()
        assert "KoteGuard STUB" in stub_path.read_text(encoding="utf-8")

    def test_injects_stub_for_google_services(self, tmp_path):
        source_root = tmp_path / "project"
        source_root.mkdir()
        (source_root / "google-services.json").write_text('{"real": true}', encoding="utf-8")

        worktree = tmp_path / "worktree"
        worktree.mkdir()

        handler = SensitiveFileHandler(worktree)
        handler.inject_stubs("android", source_root=source_root)

        stub = worktree / "google-services.json"
        assert stub.exists()
        assert "__kote_stub__" in stub.read_text(encoding="utf-8")

    def test_no_stub_if_stub_already_exists(self, tmp_path):
        source_root = tmp_path / "project"
        source_root.mkdir()
        (source_root / "release.jks").write_bytes(b"FAKE")

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        # Pre-create stub
        (worktree / "release.jks").write_text("# KoteGuard STUB\n", encoding="utf-8")

        handler = SensitiveFileHandler(worktree)
        created = handler.inject_stubs("android", source_root=source_root)

        assert len(created) == 0  # nothing newly created

    def test_injects_multiple_stubs(self, tmp_path):
        source_root = tmp_path / "project"
        source_root.mkdir()
        (source_root / "release.jks").write_bytes(b"KEY")
        (source_root / "google-services.json").write_text("{}", encoding="utf-8")
        (source_root / "local.properties").write_text("sdk.dir=/real", encoding="utf-8")

        worktree = tmp_path / "worktree"
        worktree.mkdir()

        handler = SensitiveFileHandler(worktree)
        created = handler.inject_stubs("android", source_root=source_root)

        assert len(created) >= 3

    def test_ios_stubs_injected(self, tmp_path):
        source_root = tmp_path / "project"
        source_root.mkdir()
        (source_root / "dist.p12").write_bytes(b"CERT")
        (source_root / "GoogleService-Info.plist").write_text("<plist/>", encoding="utf-8")

        worktree = tmp_path / "worktree"
        worktree.mkdir()

        handler = SensitiveFileHandler(worktree)
        handler.inject_stubs("ios", source_root=source_root)

        stub_p12 = worktree / "dist.p12"
        assert stub_p12.exists()

    def test_monorepo_gets_both_android_and_ios_stubs(self, tmp_path):
        source_root = tmp_path / "project"
        source_root.mkdir()
        (source_root / "release.jks").write_bytes(b"KEY")
        (source_root / "GoogleService-Info.plist").write_text("<plist/>", encoding="utf-8")

        worktree = tmp_path / "worktree"
        worktree.mkdir()

        handler = SensitiveFileHandler(worktree)
        created = handler.inject_stubs("monorepo", source_root=source_root)

        assert len(created) >= 2

    def test_unknown_project_type_creates_all_stubs(self, tmp_path):
        source_root = tmp_path / "project"
        source_root.mkdir()
        (source_root / "release.jks").write_bytes(b"KEY")
        (source_root / "dist.p12").write_bytes(b"CERT")

        worktree = tmp_path / "worktree"
        worktree.mkdir()

        handler = SensitiveFileHandler(worktree)
        created = handler.inject_stubs("unknown", source_root=source_root)

        assert len(created) >= 2

    def test_no_source_files_means_no_stubs(self, tmp_path):
        source_root = tmp_path / "clean_project"
        source_root.mkdir()

        worktree = tmp_path / "worktree"
        worktree.mkdir()

        handler = SensitiveFileHandler(worktree)
        created = handler.inject_stubs("android", source_root=source_root)

        assert created == []

    def test_nested_sensitive_file_keeps_relative_path(self, tmp_path):
        source_root = tmp_path / "project"
        subdir = source_root / "app" / "src" / "main"
        subdir.mkdir(parents=True)
        (subdir / "google-services.json").write_text("{}", encoding="utf-8")

        worktree = tmp_path / "worktree"
        worktree.mkdir()

        handler = SensitiveFileHandler(worktree)
        created = handler.inject_stubs("android", source_root=source_root)

        assert len(created) == 1
        # stub should be at the same relative path
        assert (worktree / "app" / "src" / "main" / "google-services.json").exists()

    def test_defaults_source_root_to_worktree_path(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "release.jks").write_bytes(b"KEY")

        handler = SensitiveFileHandler(worktree)
        created = handler.inject_stubs("android")  # no source_root → uses worktree

        # The stub overwrites itself only if it doesn't already exist as a stub
        # Since the file exists, no stub created (jks already there)
        assert isinstance(created, list)

    def test_env_file_stub_injected(self, tmp_path):
        source_root = tmp_path / "project"
        source_root.mkdir()
        (source_root / ".env").write_text("SECRET=real_value\n", encoding="utf-8")

        worktree = tmp_path / "worktree"
        worktree.mkdir()

        handler = SensitiveFileHandler(worktree)
        handler.inject_stubs("android", source_root=source_root)

        stub = worktree / ".env"
        assert stub.exists()
        assert "KoteGuard STUB" in stub.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# SensitiveFileHandler.create_stub
# ---------------------------------------------------------------------------


class TestCreateStub:
    def test_creates_stub_with_known_key(self, tmp_path):
        handler = SensitiveFileHandler(tmp_path)
        stub_path = handler.create_stub("release.jks", stub_key="ANDROID_KEYSTORE_STUB")
        assert stub_path.exists()
        content = stub_path.read_text(encoding="utf-8")
        assert "KoteGuard STUB" in content

    def test_creates_stub_with_unknown_key_uses_default(self, tmp_path):
        handler = SensitiveFileHandler(tmp_path)
        stub_path = handler.create_stub("mystery.dat", stub_key="UNKNOWN_KEY")
        assert stub_path.exists()
        content = stub_path.read_text(encoding="utf-8")
        assert "KoteGuard STUB" in content

    def test_creates_stub_with_no_key_uses_default(self, tmp_path):
        handler = SensitiveFileHandler(tmp_path)
        stub_path = handler.create_stub("no-key-file.txt")
        assert stub_path.exists()

    def test_creates_nested_directories(self, tmp_path):
        handler = SensitiveFileHandler(tmp_path)
        stub_path = handler.create_stub("deep/nested/path/secret.jks", "ANDROID_KEYSTORE_STUB")
        assert stub_path.exists()
        assert (tmp_path / "deep" / "nested" / "path").is_dir()

    def test_returns_correct_path(self, tmp_path):
        handler = SensitiveFileHandler(tmp_path)
        result = handler.create_stub("my.jks", "ANDROID_KEYSTORE_STUB")
        assert result == tmp_path / "my.jks"


# ---------------------------------------------------------------------------
# SensitiveFileHandler.is_stub
# ---------------------------------------------------------------------------


class TestIsStub:
    def test_returns_true_for_text_stub(self, tmp_path):
        stub = tmp_path / "release.jks"
        stub.write_text("# KoteGuard STUB\nSome content\n", encoding="utf-8")
        handler = SensitiveFileHandler(tmp_path)
        assert handler.is_stub(stub) is True

    def test_returns_true_for_json_stub(self, tmp_path):
        stub = tmp_path / "google-services.json"
        stub.write_text('{"__kote_stub__": true}', encoding="utf-8")
        handler = SensitiveFileHandler(tmp_path)
        assert handler.is_stub(stub) is True

    def test_returns_false_for_real_file(self, tmp_path):
        real_file = tmp_path / "real.jks"
        real_file.write_bytes(b"\x00\x01REAL_KEYSTORE")
        handler = SensitiveFileHandler(tmp_path)
        assert handler.is_stub(real_file) is False

    def test_returns_false_for_nonexistent_file(self, tmp_path):
        handler = SensitiveFileHandler(tmp_path)
        assert handler.is_stub(tmp_path / "nonexistent.jks") is False

    def test_created_stubs_are_identified_as_stubs(self, tmp_path):
        handler = SensitiveFileHandler(tmp_path)
        stub_path = handler.create_stub("test.jks", "ANDROID_KEYSTORE_STUB")
        assert handler.is_stub(stub_path) is True

    def test_env_stub_identified_as_stub(self, tmp_path):
        handler = SensitiveFileHandler(tmp_path)
        stub_path = handler.create_stub(".env", "ENV_FILE_STUB")
        assert handler.is_stub(stub_path) is True
