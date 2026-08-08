from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import fbw_harness.workspace as workspace_module
from fbw_harness.errors import HarnessError, InputError
from fbw_harness.workspace import (
    PolicyDeniedError,
    UnsupportedFileError,
    Workspace,
)


@pytest.mark.parametrize(
    "path",
    [
        "../outside.py",
        "nested/../outside.py",
        "C:/outside.py",
        "C:\\outside.py",
        "//server/share/outside.py",
        "/outside.py",
        ".git/config",
        "nested/.GIT/config",
        ".env",
        "nested/.ENV.local",
        ".fbw-recovery/original.py",
    ],
)
def test_workspace_rejects_forbidden_paths(tmp_path: Path, path: str) -> None:
    """Catches traversal, absolute-path, and protected-segment policy bypasses."""
    workspace = Workspace(tmp_path)

    with pytest.raises(PolicyDeniedError):
        workspace.resolve_safe(path, must_exist=False)


def test_workspace_policy_errors_are_stable_harness_errors() -> None:
    """Catches workspace failures escaping the harness error hierarchy."""
    assert issubclass(PolicyDeniedError, HarnessError)
    assert issubclass(UnsupportedFileError, HarnessError)


def test_workspace_requires_an_existing_non_sensitive_directory(tmp_path: Path) -> None:
    """Catches unsafe workspace roots being accepted before path operations."""
    missing = tmp_path / "missing"
    regular_file = tmp_path / "file.txt"
    regular_file.write_text("text", encoding="utf-8")

    with pytest.raises(InputError):
        Workspace(missing)
    with pytest.raises(InputError):
        Workspace(regular_file)
    with pytest.raises(InputError):
        Workspace(Path(Path.cwd().anchor))
    with pytest.raises(InputError):
        Workspace(Path.home())


def test_read_file_returns_relative_path_hash_and_text(tmp_path: Path) -> None:
    """Catches text, path, or digest corruption in a normal workspace read."""
    (tmp_path / "a.py").write_bytes(b"x = 1\n")

    snapshot = Workspace(tmp_path).read_file("a.py")

    assert snapshot.path == "a.py"
    assert snapshot.text == "x = 1\n"
    assert snapshot.sha256 == "9e26bf369911c45c243c684147b23fc9e1dcfcf257d299a1c632016a6fcd33f4"


@pytest.mark.parametrize("directory", [".venv", "venv", "__pycache__", "node_modules"])
def test_read_file_rejects_paths_in_discovery_ignored_directories(
    tmp_path: Path, directory: str
) -> None:
    """Catches direct reads bypassing directories hidden from discovery."""
    target = tmp_path / directory / "visible.txt"
    target.parent.mkdir()
    target.write_text("secret-adjacent", encoding="utf-8")

    with pytest.raises(PolicyDeniedError):
        Workspace(tmp_path).read_file(f"{directory}/visible.txt")


@pytest.mark.parametrize("payload", [b"\x00text", b"\xff\xfe"])
def test_read_file_rejects_binary_content_even_with_text_extension(
    tmp_path: Path, payload: bytes
) -> None:
    """Catches extension-based binary detection and permissive UTF-8 decoding."""
    (tmp_path / "looks-safe.py").write_bytes(payload)

    with pytest.raises(UnsupportedFileError):
        Workspace(tmp_path).read_file("looks-safe.py")


def test_read_file_enforces_configurable_byte_limit(tmp_path: Path) -> None:
    """Catches reads exceeding the configured bounded-I/O limit."""
    (tmp_path / "large.txt").write_bytes(b"12345")

    with pytest.raises(UnsupportedFileError):
        Workspace(tmp_path, file_size_limit_bytes=4).read_file("large.txt")


def test_list_files_is_sorted_and_skips_ignored_or_unsupported_entries(tmp_path: Path) -> None:
    """Catches nondeterministic discovery or one bad file aborting/skewing the listing."""
    (tmp_path / "z.txt").write_text("z", encoding="utf-8")
    (tmp_path / "extensionless").write_text("utf8", encoding="utf-8")
    (tmp_path / "binary.py").write_bytes(b"\x00binary")
    (tmp_path / "invalid.txt").write_bytes(b"\xff")
    (tmp_path / "large.txt").write_bytes(b"12345")
    (tmp_path / ".env.example").write_text("TOKEN=value", encoding="utf-8")
    for ignored in (
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "node_modules",
        ".fbw-recovery",
    ):
        hidden = tmp_path / ignored
        hidden.mkdir()
        (hidden / "hidden.txt").write_text("hidden", encoding="utf-8")

    files = Workspace(tmp_path, file_size_limit_bytes=4).list_files()

    assert files == ("extensionless", "z.txt")


def test_resolve_safe_rejects_symlinks_at_any_path_level(tmp_path: Path) -> None:
    """Catches a symlinked intermediate directory escaping or aliasing the workspace."""
    actual = tmp_path / "actual"
    actual.mkdir()
    (actual / "file.txt").write_text("text", encoding="utf-8")
    link = tmp_path / "link"
    try:
        link.symlink_to(actual, target_is_directory=True)
    except OSError:
        link.mkdir()
        (link / "file.txt").write_text("text", encoding="utf-8")
        real_is_symlink = Path.is_symlink

        def is_symlink_at_link(path: Path) -> bool:
            if os.path.normcase(os.fspath(path)) == os.path.normcase(os.fspath(link)):
                return True
            return real_is_symlink(path)

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(Path, "is_symlink", is_symlink_at_link)
        try:
            with pytest.raises(PolicyDeniedError):
                Workspace(tmp_path).resolve_safe("link/file.txt", must_exist=True)
        finally:
            monkeypatch.undo()
        return

    with pytest.raises(PolicyDeniedError):
        Workspace(tmp_path).resolve_safe("link/file.txt", must_exist=True)


def test_resolve_safe_rejects_windows_junction_or_reparse_attribute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches junctions and non-symlink reparse points at an intermediate component."""
    target = tmp_path / "target"
    target.mkdir()
    (target / "file.txt").write_text("text", encoding="utf-8")
    junction = tmp_path / "junction"

    created = False
    if os.name == "nt":
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)],
            capture_output=True,
            check=False,
            text=True,
        )
        created = result.returncode == 0

    workspace = Workspace(tmp_path)
    if created:
        with pytest.raises(PolicyDeniedError):
            workspace.resolve_safe("junction/file.txt", must_exist=True)
        return

    junction.mkdir()
    (junction / "file.txt").write_text("text", encoding="utf-8")
    real_lstat = os.lstat

    def lstat_with_reparse(path: os.PathLike[str] | str) -> os.stat_result | SimpleNamespace:
        result = real_lstat(path)
        if os.path.normcase(os.fspath(path)) == os.path.normcase(os.fspath(junction)):
            return SimpleNamespace(
                st_mode=result.st_mode,
                st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
            )
        return result

    monkeypatch.setattr(workspace_module.os, "lstat", lstat_with_reparse)

    with pytest.raises(PolicyDeniedError):
        workspace.resolve_safe("junction/file.txt", must_exist=True)
