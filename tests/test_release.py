"""Tests for release prerequisites, archive layout and changelog extraction."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from zipfile import ZipFile

import pytest

from scripts.release import INTEGRATION, ROOT, build_archive, check_release, release_notes


@pytest.fixture
def release_root(tmp_path: Path) -> Path:
    """Create a manifest with different integration and library versions."""
    source = tmp_path / INTEGRATION
    source.mkdir(parents=True)
    (source / "manifest.json").write_text(
        json.dumps({"version": "0.2.0", "requirements": ["sabatark==0.1.0"]})
    )
    return tmp_path


def test_archive_root_and_contents(tmp_path: Path) -> None:
    output = tmp_path / "sabatark.zip"
    build_archive(output)
    with ZipFile(output) as archive:
        names = set(archive.namelist())
        assert {
            "manifest.json",
            "__init__.py",
            "event.py",
            "options_flow.py",
            "translations/en.json",
            "brand/icon.png",
            "brand/logo.png",
        } <= names
        assert archive.read("manifest.json") == (ROOT / INTEGRATION / "manifest.json").read_bytes()
        assert not any(name.startswith("custom_components/") for name in names)
        assert not any("__pycache__" in name or name.endswith((".pyc", ".pyo")) for name in names)
        assert archive.testzip() is None


def test_archive_excludes_cache_files(tmp_path: Path) -> None:
    integration = tmp_path / INTEGRATION
    cache = integration / "__pycache__"
    cache.mkdir(parents=True)
    (integration / "manifest.json").write_text('{"version": "0.1.0"}')
    (integration / "module.py").write_text('"""Synthetic module."""\n')
    (cache / "module.cpython-314.pyc").write_bytes(b"fake bytecode")
    (integration / "old.pyc").write_bytes(b"fake bytecode")
    (integration / "old.pyo").write_bytes(b"fake bytecode")
    (integration / ".DS_Store").write_bytes(b"fake metadata")
    output = tmp_path / "sabatark.zip"
    build_archive(output, tmp_path)
    with ZipFile(output) as archive:
        assert set(archive.namelist()) == {"manifest.json", "module.py"}
    with pytest.raises(ValueError, match="outside the integration"):
        build_archive(integration / "sabatark.zip", tmp_path)


def test_tag_matches_before_network_access(release_root: Path) -> None:
    with patch("scripts.release.urlopen") as request:
        with pytest.raises(ValueError, match=r"must be v0\.2\.0"):
            check_release("v9.9.9", release_root)
        request.assert_not_called()


def test_exact_library_version_on_pypi(release_root: Path) -> None:
    response = MagicMock()
    response.__enter__.return_value.status = 200
    with patch("scripts.release.urlopen", return_value=response) as request:
        assert check_release("v0.2.0", release_root) == "0.2.0"
        request.assert_called_once_with("https://pypi.org/pypi/sabatark/0.1.0/json", timeout=20)


@pytest.mark.parametrize(
    "requirements",
    [["sabatark>=0.1.0"], ["other==0.1.0"], ["sabatark==0.1.0", "sabatark==0.2.0"]],
)
def test_release_requires_one_exact_library_pin(
    release_root: Path, requirements: list[str]
) -> None:
    (release_root / INTEGRATION / "manifest.json").write_text(
        json.dumps({"version": "0.2.0", "requirements": requirements})
    )
    with patch("scripts.release.urlopen") as request:
        with pytest.raises(ValueError, match="one exact sabatark==X"):
            check_release("v0.2.0", release_root)
        request.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    [
        HTTPError("https://pypi.org", 404, "Synthetic missing version", None, None),
        URLError("Synthetic network failure"),
        TimeoutError(),
    ],
)
def test_missing_library_blocks_release(failure: Exception, release_root: Path) -> None:
    with (
        patch("scripts.release.urlopen", side_effect=failure),
        pytest.raises(ValueError, match="Release python-sabatark first"),
    ):
        check_release("v0.2.0", release_root)


def test_non_success_status_blocks_release(release_root: Path) -> None:
    response = MagicMock()
    response.__enter__.return_value.status = 503
    with (
        patch("scripts.release.urlopen", return_value=response),
        pytest.raises(ValueError, match="Release python-sabatark first"),
    ):
        check_release("v0.2.0", release_root)


def test_notes_use_only_requested_version(tmp_path: Path) -> None:
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [0.2.0]\n\nNew release.\n\n## [0.1.0]\n\nInitial release.\n"
    )
    assert release_notes("0.2.0", tmp_path) == "New release.\n"
    assert release_notes("0.1.0", tmp_path) == "Initial release.\n"
    with pytest.raises(ValueError, match="no release notes"):
        release_notes("0.3.0", tmp_path)
    assert "wall-switch" in release_notes("0.1.0")
