"""Tests for the sensitive file handler."""

from __future__ import annotations

from pathlib import Path

import pytest

from koteguard.sensitive_files import (
    ANDROID_SENSITIVE,
    IOS_SENSITIVE,
    SensitiveFileHandler,
    _resolve_patterns,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _write(path: Path, content: str = "real content") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# _resolve_patterns
# ---------------------------------------------------------------------------


class TestResolvePatterns:
    def test_android(self):
        patterns = _resolve_patterns("android")
        assert "*.jks" in patterns
        assert "google-services.json" in patterns
        assert "*.p12" not in patterns

    def test_ios(self):
        patterns = _resolve_patterns("ios")
        assert "*.p12" in patterns
        assert "*.mobileprovision" in patterns
        assert "*.jks" not in patterns

    def test_monorepo(self):
        patterns = _resolve_patterns("monorepo")
        assert "*.jks" in patterns
        assert "*.p12" in patterns

    def test_unknown(self):
        patterns = _resolve_patterns("unknown")
        assert "*.jks" in patterns
        assert "*.p12" in patterns

    def test_flutter(self):
        patterns = _resolve_patterns("flutter")
        assert "*.jks" in patterns
        assert "*.p12" in patterns


# ---------------------------------------------------------------------------
# SensitiveFileHandler
# ---------------------------------------------------------------------------


class TestSensitiveFileHandler:
    def test_create_stub_manual(self, tmp_path):
        handler = SensitiveFileHandler(tmp_path)
        stub = handler.create_stub("app/release.jks", "ANDROID_KEYSTORE_STUB")
        assert stub.exists()
        assert "KoteGuard STUB" in stub.read_text()

    def test_is_stub_true(self, tmp_path):
        handler = SensitiveFileHandler(tmp_path)
        stub = handler.create_stub("test.jks", "ANDROID_KEYSTORE_STUB")
        assert handler.is_stub(stub) is True

    def test_is_stub_false_for_real_file(self, tmp_path):
        real = _write(tmp_path / "real.jks", "binary content")
        handler = SensitiveFileHandler(tmp_path)
        assert handler.is_stub(real) is False

    def test_inject_stubs_google_services(self, tmp_path):
        # Create a fake source root with google-services.json
        source = tmp_path / "source"
        _write(source / "app" / "google-services.json", '{"real": true}')

        worktree = tmp_path / "worktree"
        worktree.mkdir()

        handler = SensitiveFileHandler(worktree)
        created = handler.inject_stubs("android", source_root=source)

        assert len(created) == 1
        stub_content = created[0].read_text()
        assert "__kote_stub__" in stub_content

    def test_inject_stubs_no_sensitive_files(self, tmp_path):
        source = tmp_path / "source"
        source.mkdir()
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        handler = SensitiveFileHandler(worktree)
        created = handler.inject_stubs("android", source_root=source)
        assert created == []

    def test_stub_not_duplicated(self, tmp_path):
        """If a stub already exists, don't recreate it."""
        source = tmp_path / "source"
        _write(source / "google-services.json", '{"real": true}')

        worktree = tmp_path / "worktree"
        worktree.mkdir()

        handler = SensitiveFileHandler(worktree)
        created1 = handler.inject_stubs("android", source_root=source)
        created2 = handler.inject_stubs("android", source_root=source)

        assert len(created1) == 1
        assert len(created2) == 0  # Already exists

    def test_google_service_info_plist_stub(self, tmp_path):
        source = tmp_path / "source"
        _write(source / "GoogleService-Info.plist", "<plist>real</plist>")

        worktree = tmp_path / "worktree"
        worktree.mkdir()

        handler = SensitiveFileHandler(worktree)
        created = handler.inject_stubs("ios", source_root=source)
        assert len(created) == 1
        assert "kote_stub" in created[0].read_text()

    def test_local_properties_stub(self, tmp_path):
        handler = SensitiveFileHandler(tmp_path)
        stub = handler.create_stub("local.properties", "LOCAL_PROPERTIES_STUB")
        content = stub.read_text()
        assert "KoteGuard STUB" in content
        assert "sdk.dir" in content
