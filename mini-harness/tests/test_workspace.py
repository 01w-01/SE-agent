from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Self

import pytest

import fbw_harness.workspace as workspace_module
from fbw_harness.errors import HarnessError, InputError
from fbw_harness.workspace import (
    PolicyDeniedError,
    UnsupportedFileError,
    Workspace,
    WorkspaceLimitError,
)


def _create_junction(link: Path, target: Path) -> bool:
    if os.name != "nt":
        return False
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        check=False,
        text=True,
    )
    return result.returncode == 0


def _mark_path_as_reparse(monkeypatch: pytest.MonkeyPatch, marked: Path) -> None:
    real_lstat = os.lstat

    def lstat_with_reparse(path: os.PathLike[str] | str) -> os.stat_result | SimpleNamespace:
        result = real_lstat(path)
        if os.path.normcase(os.fspath(path)) == os.path.normcase(os.fspath(marked)):
            return SimpleNamespace(
                st_mode=result.st_mode,
                st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
            )
        return result

    monkeypatch.setattr(workspace_module.os, "lstat", lstat_with_reparse)


class _ChangedStat:
    def __init__(self, metadata: os.stat_result, field: str) -> None:
        self._metadata = metadata
        self._field = field

    def __getattr__(self, name: str) -> object:
        value = getattr(self._metadata, name)
        if name == self._field:
            return value + 1
        return value


class _BoundedScandir:
    def __init__(self) -> None:
        self._count = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def __iter__(self) -> _BoundedScandir:
        return self

    def __next__(self) -> SimpleNamespace:
        self._count += 1
        if self._count > 10_000:
            raise AssertionError("scandir consumed an entry beyond the inspection limit")
        return SimpleNamespace(name=f"entry-{self._count:05}")


def _assert_no_exception_chain(error: BaseException) -> None:
    assert error.__cause__ is None
    assert error.__context__ is None


@pytest.mark.parametrize(
    "path",
    [
        "../outside.py",
        "nested/../outside.py",
        "C:/outside.py",
        "C:\\outside.py",
        "C:drive-relative.py",
        "//server/share/outside.py",
        "//./PhysicalDrive0",
        "//?/C:/outside.py",
        "/outside.py",
        "NUL",
        "safe.txt::$DATA",
        ".git/config",
        "nested/.GIT/config",
        ".env",
        "nested/.ENV.local",
        ".fbw-recovery/original.py",
        ".credentials/token",
        ".secrets/token",
        ".aws/credentials",
        ".ssh/id_ed25519",
        ".azure/accessTokens.json",
        "credentials.json",
        "build/output.txt",
        "dist/output.txt",
        ".eggs/package",
        "package.EGG-INFO/PKG-INFO",
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
    assert issubclass(WorkspaceLimitError, HarnessError)


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


@pytest.mark.parametrize("protected", [".SSH", "build", "project.EGG-INFO"])
def test_workspace_rejects_a_root_inside_a_protected_tree(tmp_path: Path, protected: str) -> None:
    """Catches selecting a nested workspace that bypasses a protected ancestor."""
    root = tmp_path / protected / "workspace"
    root.mkdir(parents=True)

    with pytest.raises(InputError):
        Workspace(root)


def test_workspace_rejects_a_reparse_point_in_the_root_ancestor_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a normal-looking root nested below a junction/reparse ancestor."""
    target = tmp_path / "target"
    root = target / "workspace"
    root.mkdir(parents=True)
    junction = tmp_path / "junction"
    created = _create_junction(junction, target)

    if created:
        with pytest.raises(InputError):
            Workspace(junction / "workspace")
        return

    apparent_root = tmp_path / "apparent" / "workspace"
    apparent_root.mkdir(parents=True)
    _mark_path_as_reparse(monkeypatch, tmp_path / "apparent")

    with pytest.raises(InputError):
        Workspace(apparent_root)


def test_resolve_checks_existing_reparse_chain_before_path_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches Path.resolve running before an existing reparse component is rejected."""
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir()
    (unsafe / "file.txt").write_text("text", encoding="utf-8")
    workspace = Workspace(tmp_path)
    _mark_path_as_reparse(monkeypatch, unsafe)
    real_resolve = Path.resolve

    def guarded_resolve(path: Path, *args: object, **kwargs: object) -> Path:
        if path == unsafe / "file.txt":
            raise AssertionError("Path.resolve ran before the reparse check")
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", guarded_resolve)

    with pytest.raises(PolicyDeniedError):
        workspace.resolve_safe("unsafe/file.txt", must_exist=True)


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


@pytest.mark.parametrize("field", ["st_dev", "st_ino", "st_size", "st_mtime_ns"])
def test_read_file_rejects_path_to_opened_handle_metadata_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    """Catches replacement or mutation between path stat and opening the file handle."""
    (tmp_path / "file.txt").write_text("stable", encoding="utf-8")
    real_fstat = os.fstat

    def changed_opened_stat(descriptor: int) -> _ChangedStat:
        return _ChangedStat(real_fstat(descriptor), field)

    monkeypatch.setattr(workspace_module.os, "fstat", changed_opened_stat)

    with pytest.raises(UnsupportedFileError):
        Workspace(tmp_path).read_file("file.txt")


@pytest.mark.parametrize("field", ["st_dev", "st_ino", "st_size", "st_mtime_ns"])
def test_read_file_rejects_opened_handle_metadata_changes_during_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    """Catches an opened file changing identity, size, or mtime while being read."""
    (tmp_path / "file.txt").write_text("stable", encoding="utf-8")
    real_fstat = os.fstat
    call_count = 0

    def changed_post_read_stat(descriptor: int) -> os.stat_result | _ChangedStat:
        nonlocal call_count
        call_count += 1
        metadata = real_fstat(descriptor)
        if call_count == 2:
            return _ChangedStat(metadata, field)
        return metadata

    monkeypatch.setattr(workspace_module.os, "fstat", changed_post_read_stat)

    with pytest.raises(UnsupportedFileError):
        Workspace(tmp_path).read_file("file.txt")


def test_decode_failure_does_not_expose_the_unicode_error_chain(tmp_path: Path) -> None:
    """Catches invalid external bytes remaining reachable through exception chaining."""
    (tmp_path / "invalid.txt").write_bytes(b"\xffprivate")

    with pytest.raises(UnsupportedFileError) as caught:
        Workspace(tmp_path).read_file("invalid.txt")

    _assert_no_exception_chain(caught.value)


def test_resolve_failure_does_not_expose_the_path_error_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches external paths remaining reachable through a mapped resolve error."""
    workspace = Workspace(tmp_path)

    def failing_resolve(path: Path, *args: object, **kwargs: object) -> Path:
        raise OSError(r"sensitive C:\external\private.txt")

    monkeypatch.setattr(Path, "resolve", failing_resolve)

    with pytest.raises(PolicyDeniedError) as caught:
        workspace.resolve_safe("missing.txt", must_exist=False)

    _assert_no_exception_chain(caught.value)


def test_open_failure_does_not_expose_the_path_error_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches external paths remaining reachable through a mapped open error."""
    target = tmp_path / "file.txt"
    target.write_text("text", encoding="utf-8")
    real_open = Path.open

    def failing_open(path: Path, *args: object, **kwargs: object) -> object:
        if path == target:
            raise OSError(r"sensitive C:\external\private.txt")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)

    with pytest.raises(InputError) as caught:
        Workspace(tmp_path).read_file("file.txt")

    _assert_no_exception_chain(caught.value)


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
        ".credentials",
        ".secrets",
        ".aws",
        ".ssh",
        ".azure",
        "build",
        "dist",
        ".eggs",
        "package.egg-info",
    ):
        hidden = tmp_path / ignored
        hidden.mkdir()
        (hidden / "hidden.txt").write_text("hidden", encoding="utf-8")

    files = Workspace(tmp_path, file_size_limit_bytes=4).list_files()

    assert files == ("extensionless", "z.txt")


def test_list_files_returns_nested_paths_in_posix_sort_order(tmp_path: Path) -> None:
    """Catches traversal order or Windows separators leaking into the public result."""
    for relative in ("z/top.txt", "a/z.txt", "a/b.txt"):
        target = tmp_path / relative
        target.parent.mkdir(exist_ok=True)
        target.write_text("text", encoding="utf-8")

    assert Workspace(tmp_path).list_files() == ("a/b.txt", "a/z.txt", "z/top.txt")


def test_read_file_rejects_a_directory_as_a_special_entry(tmp_path: Path) -> None:
    """Catches non-regular filesystem entries being opened as text files."""
    (tmp_path / "directory").mkdir()

    with pytest.raises(UnsupportedFileError):
        Workspace(tmp_path).read_file("directory")


def test_list_files_rechecks_root_ancestors_before_the_first_scandir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a root ancestor becoming reparse-backed after Workspace construction."""
    workspace = Workspace(tmp_path)
    _mark_path_as_reparse(monkeypatch, tmp_path.parent)

    with pytest.raises(PolicyDeniedError):
        workspace.list_files()


def test_list_files_rechecks_a_pending_directory_chain_before_scandir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a queued directory becoming a reparse point before its scandir."""
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "file.txt").write_text("text", encoding="utf-8")
    real_is_reparse = workspace_module._is_reparse_point
    nested_checks = 0

    def staged_reparse(path: Path) -> bool:
        nonlocal nested_checks
        if path == nested:
            nested_checks += 1
            return nested_checks >= 2
        return real_is_reparse(path)

    monkeypatch.setattr(workspace_module, "_is_reparse_point", staged_reparse)

    with pytest.raises(PolicyDeniedError):
        Workspace(tmp_path).list_files()


def test_list_files_raises_when_the_return_limit_is_reached(tmp_path: Path) -> None:
    """Catches discovery silently returning or truncating at 1,000 text files."""
    for index in range(1_000):
        (tmp_path / f"file-{index:04}.txt").touch()

    with pytest.raises(WorkspaceLimitError):
        Workspace(tmp_path).list_files()


def test_list_files_raises_when_the_inspection_limit_is_reached(tmp_path: Path) -> None:
    """Catches ignored entries bypassing the 10,000-entry discovery work bound."""
    for index in range(10_000):
        (tmp_path / f".env-{index:05}").touch()

    with pytest.raises(WorkspaceLimitError):
        Workspace(tmp_path).list_files()


def test_list_files_does_not_consume_an_entry_beyond_the_inspection_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches eager scandir sorting reading item 10,001 before enforcing the bound."""
    monkeypatch.setattr(workspace_module.os, "scandir", lambda path: _BoundedScandir())

    with pytest.raises(WorkspaceLimitError):
        Workspace(tmp_path).list_files()


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
