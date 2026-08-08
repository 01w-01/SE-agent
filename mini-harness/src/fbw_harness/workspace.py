from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from .errors import HarnessError, InputError

_IGNORED_DIRECTORY_NAMES = frozenset(
    {
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
    }
)
_PROTECTED_EXACT_NAMES = _IGNORED_DIRECTORY_NAMES | {"credentials.json"}
_WINDOWS_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)
_MAX_RETURNED_FILES = 1_000
_MAX_INSPECTED_ENTRIES = 10_000


class PolicyDeniedError(HarnessError):
    """A workspace path was rejected by a stable security policy."""


class UnsupportedFileError(HarnessError):
    """A workspace entry cannot be handled as a bounded UTF-8 regular file."""


class WorkspaceLimitError(HarnessError):
    """Workspace discovery reached a stable resource limit."""


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    path: str
    text: str
    sha256: str


class Workspace:
    def __init__(self, root: Path, file_size_limit_bytes: int = 262_144) -> None:
        if type(file_size_limit_bytes) is not int or file_size_limit_bytes <= 0:
            raise InputError("workspace file size limit must be a positive integer")

        candidate = Path(root)
        absolute = Path(os.path.abspath(candidate))
        if absolute == Path(absolute.anchor):
            raise InputError("workspace root must not be a disk root")
        if any(_is_protected_name(part) for part in absolute.parts):
            raise InputError("workspace root must not be inside a protected tree")
        try:
            _reject_reparse_path(absolute, InputError)
            if not candidate.exists() or not candidate.is_dir():
                raise InputError("workspace root must be an existing directory")
            resolved = candidate.resolve(strict=True)
        except InputError:
            raise
        except (OSError, RuntimeError):
            root_failed = True
        else:
            root_failed = False
        if root_failed:
            raise InputError("workspace root cannot be resolved")

        try:
            home = Path.home().resolve(strict=False)
        except (OSError, RuntimeError):
            home_failed = True
        else:
            home_failed = False
        if home_failed:
            raise InputError("user home directory cannot be resolved")
        if _same_path(resolved, home):
            raise InputError("workspace root must not be the user home directory")
        if any(_is_protected_name(part) for part in resolved.parts):
            raise InputError("workspace root must not be inside a protected tree")

        self.root = resolved
        self.file_size_limit_bytes = file_size_limit_bytes

    def resolve_safe(self, relative: str, *, must_exist: bool) -> Path:
        parts = _relative_parts(relative)
        if any(_is_protected_name(part) for part in parts):
            raise PolicyDeniedError("workspace path contains a protected segment")

        unresolved = self.root.joinpath(*parts)
        self._reject_reparse_chain(unresolved)
        try:
            resolved = unresolved.resolve(strict=False)
        except (OSError, RuntimeError):
            resolve_failed = True
        else:
            resolve_failed = False
        if resolve_failed:
            raise PolicyDeniedError("workspace path cannot be resolved safely")
        if not _is_within(self.root, resolved):
            raise PolicyDeniedError("workspace path escapes the workspace root")

        if must_exist:
            try:
                exists = resolved.exists()
            except OSError:
                exists_failed = True
            else:
                exists_failed = False
            if exists_failed:
                raise InputError("workspace path cannot be inspected")
            if not exists:
                raise InputError("workspace path does not exist")
        return resolved

    def list_files(self) -> tuple[str, ...]:
        discovered: list[str] = []
        inspected_entries = 0
        pending = [self.root]
        while pending:
            directory = pending.pop()
            _reject_reparse_path(directory, PolicyDeniedError)
            try:
                with os.scandir(directory) as iterator:
                    entries = []
                    for entry in iterator:
                        inspected_entries += 1
                        if inspected_entries >= _MAX_INSPECTED_ENTRIES:
                            raise WorkspaceLimitError("workspace inspection limit reached")
                        entries.append(entry)
            except OSError:
                continue
            entries.sort(key=lambda entry: entry.name.casefold())
            for entry in entries:
                path = Path(entry.path)
                canonical_name = _canonical_windows_name(entry.name)
                try:
                    if _is_reparse_point(path):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if (
                            canonical_name not in _IGNORED_DIRECTORY_NAMES
                            and not _is_protected_name(canonical_name)
                        ):
                            pending.append(path)
                        continue
                    if not entry.is_file(follow_symlinks=False) or _is_protected_name(entry.name):
                        continue
                    relative = path.relative_to(self.root).as_posix()
                    self.read_file(relative)
                except (HarnessError, OSError, ValueError):
                    continue
                discovered.append(relative)
                if len(discovered) >= _MAX_RETURNED_FILES:
                    raise WorkspaceLimitError("workspace file return limit reached")
        return tuple(sorted(discovered))

    def read_file(self, relative: str) -> FileSnapshot:
        parts = _relative_parts(relative)
        if any(_canonical_windows_name(part) in _IGNORED_DIRECTORY_NAMES for part in parts[:-1]):
            raise PolicyDeniedError("workspace path is inside an ignored directory")

        target = self.resolve_safe(relative, must_exist=True)
        try:
            before = target.stat(follow_symlinks=False)
        except OSError:
            stat_failed = True
        else:
            stat_failed = False
        if stat_failed:
            raise InputError("workspace file cannot be inspected")
        _validate_regular_file(before, self.file_size_limit_bytes)

        try:
            with target.open("rb") as stream:
                opened = os.fstat(stream.fileno())
                _validate_regular_file(opened, self.file_size_limit_bytes)
                if not _same_file_state(before, opened):
                    raise UnsupportedFileError("workspace file changed before opening")
                payload = stream.read(self.file_size_limit_bytes + 1)
                after = os.fstat(stream.fileno())
        except UnsupportedFileError:
            raise
        except OSError:
            read_failed = True
        else:
            read_failed = False
        if read_failed:
            raise InputError("workspace file cannot be read")

        if not _same_file_state(opened, after):
            raise UnsupportedFileError("workspace file changed while being read")
        if len(payload) > self.file_size_limit_bytes:
            raise UnsupportedFileError("workspace file exceeds the configured size limit")
        if b"\x00" in payload:
            raise UnsupportedFileError("workspace file contains binary data")
        try:
            text = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            decode_failed = True
        else:
            decode_failed = False
        if decode_failed:
            raise UnsupportedFileError("workspace file is not valid UTF-8 text")

        path = target.relative_to(self.root).as_posix()
        return FileSnapshot(path=path, text=text, sha256=hashlib.sha256(payload).hexdigest())

    def _reject_reparse_chain(self, path: Path) -> None:
        _reject_reparse_path(path, PolicyDeniedError)


def _relative_parts(relative: str) -> tuple[str, ...]:
    if not isinstance(relative, str) or not relative:
        raise PolicyDeniedError("workspace path must be a non-empty relative string")
    if "\x00" in relative:
        raise PolicyDeniedError("workspace path contains an invalid character")

    windows_path = PureWindowsPath(relative)
    normalized = relative.replace("\\", "/")
    if windows_path.drive or windows_path.is_absolute() or normalized.startswith("/"):
        raise PolicyDeniedError("absolute workspace paths are not allowed")

    parts = PurePosixPath(normalized).parts
    if not parts or any(part == ".." for part in parts):
        raise PolicyDeniedError("workspace path traversal is not allowed")
    for part in parts:
        canonical = _canonical_windows_name(part)
        stem = canonical.split(".", 1)[0]
        if (
            not canonical
            or canonical != part.casefold()
            or ":" in part
            or any(character in part for character in "*?")
            or any(ord(character) < 32 for character in part)
            or stem in _WINDOWS_RESERVED_NAMES
        ):
            raise PolicyDeniedError("workspace path contains an unsafe Windows segment")
    return tuple(parts)


def _canonical_windows_name(name: str) -> str:
    return name.rstrip(" .").casefold()


def _is_protected_name(name: str) -> bool:
    canonical = _canonical_windows_name(name)
    return (
        canonical in _PROTECTED_EXACT_NAMES
        or canonical.startswith(".env")
        or canonical.endswith(".egg-info")
    )


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def _is_within(root: Path, target: Path) -> bool:
    root_text = os.path.normcase(os.path.abspath(root))
    target_text = os.path.normcase(os.path.abspath(target))
    try:
        common = os.path.commonpath((root_text, target_text))
    except ValueError:
        return False
    return os.path.normcase(common) == root_text


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    metadata = os.lstat(path)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _reject_reparse_path(path: Path, error_type: type[PolicyDeniedError | InputError]) -> None:
    inspection_failed = False
    for current in reversed((path, *path.parents)):
        try:
            if _is_reparse_point(current):
                raise error_type("workspace path contains a reparse point")
        except FileNotFoundError:
            break
        except OSError:
            inspection_failed = True
            break
    if inspection_failed:
        raise error_type("workspace path cannot be inspected safely")


def _validate_regular_file(metadata: os.stat_result, size_limit: int) -> None:
    if not stat.S_ISREG(metadata.st_mode):
        raise UnsupportedFileError("workspace entry is not a regular file")
    attributes = getattr(metadata, "st_file_attributes", 0)
    if attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise UnsupportedFileError("workspace file is a reparse point")
    if metadata.st_size > size_limit:
        raise UnsupportedFileError("workspace file exceeds the configured size limit")


def _same_file_state(left: os.stat_result, right: os.stat_result) -> bool:
    return all(
        getattr(left, field) == getattr(right, field)
        for field in ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    )
