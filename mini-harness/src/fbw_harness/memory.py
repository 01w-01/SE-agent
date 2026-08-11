from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import ProjectMemory

_ALLOWED_FIELDS = frozenset({"version", "project_notes", "last_success_summary", "updated_at"})
_TEXT_FIELDS = frozenset({"project_notes", "last_success_summary"})
_MAX_TEXT_CHARS = 2_000
_MAX_FILE_BYTES = 128 * 1024
_CORRUPT_MEMORY_WARNING = "Project memory was ignored because its file was invalid."
_SECRET_NAME_PATTERN = (
    r"(?:api[\s._-]*key|access[\s._-]*key(?:[\s._-]*id)?|"
    r"access[\s._-]*token|authorization|bearer|client[\s._-]*secret|"
    r"credential|file[\s._-]*content|password|private[\s._-]*key|"
    r"refresh[\s._-]*token|secret|token)"
)
_SECRET_FIELD_RE = re.compile(rf"(?i)[\"']?\s*{_SECRET_NAME_PATTERN}[\"']?\s*[:=]")
_UTC_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")

_MISSING = "missing"
_VALID = "valid"
_QUARANTINED = "quarantined"
_UNREADABLE = "unreadable"
_UNSAFE = "unsafe"


class _MemoryTooLarge(Exception):
    pass


class _MemoryUnreadable(Exception):
    pass


@dataclass(frozen=True, slots=True)
class _LoadOutcome:
    status: str
    memory: ProjectMemory | None = None
    notify: bool = False


class JsonProjectMemoryStore:
    """A deliberately small, opt-in JSON store for non-secret project memory."""

    def __init__(self, path: Path | None, *, enabled: bool) -> None:
        self._path = Path(path) if path is not None else None
        self._enabled = type(enabled) is bool and enabled

    def load(self) -> ProjectMemory | None:
        outcome = self._load_internal()
        if outcome.notify:
            _notify_corrupt_memory()
        return outcome.memory

    def save_success(self, summary: str) -> None:
        if not self._ready() or not _safe_text(summary):
            return
        path = self._path
        assert path is not None
        outcome = self._load_internal()
        if outcome.notify:
            _notify_corrupt_memory()
        if outcome.status not in {_MISSING, _VALID, _QUARANTINED}:
            return
        project_notes = outcome.memory.project_notes if outcome.memory is not None else ""
        payload = {
            "version": 1,
            "project_notes": project_notes,
            "last_success_summary": summary,
            "updated_at": _utc_now(),
        }
        _atomic_write(path, payload)

    def clear(self) -> None:
        if not self._ready():
            return
        path = self._path
        assert path is not None
        if not _path_is_safe(path) or _target_state(path) != "regular":
            return
        try:
            path.unlink()
        except (OSError, TypeError, ValueError):
            return

    def _ready(self) -> bool:
        return self._enabled and self._path is not None and _path_is_safe(self._path)

    def _load_internal(self) -> _LoadOutcome:
        if not self._ready():
            return _LoadOutcome(_UNSAFE)
        path = self._path
        assert path is not None
        state = _target_state(path)
        if state == "missing":
            return _LoadOutcome(_MISSING)
        if state != "regular":
            return _LoadOutcome(_UNSAFE)
        try:
            raw = _read_bytes(path)
        except _MemoryTooLarge:
            return _corrupt_outcome(path)
        except (_MemoryUnreadable, OSError, ValueError):
            return _LoadOutcome(_UNREADABLE)
        try:
            payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
            memory = _parse_memory(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
            return _corrupt_outcome(path)
        return _LoadOutcome(_VALID, memory)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate memory field")
        result[key] = value
    return result


def _parse_memory(payload: object) -> ProjectMemory:
    if not isinstance(payload, dict) or set(payload) != _ALLOWED_FIELDS:
        raise ValueError("invalid memory schema")
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise ValueError("invalid memory version")
    for field in _TEXT_FIELDS:
        value = payload[field]
        if not _safe_text(value):
            raise ValueError("invalid memory text")
    updated_at = payload["updated_at"]
    if not _safe_text(updated_at) or not _valid_utc_timestamp(updated_at):
        raise ValueError("invalid memory timestamp")
    return ProjectMemory(
        version=payload["version"],
        project_notes=payload["project_notes"],
        last_success_summary=payload["last_success_summary"],
        updated_at=updated_at,
    )


def _safe_text(value: object) -> bool:
    if type(value) is not str or len(value) > _MAX_TEXT_CHARS:
        return False
    return _SECRET_FIELD_RE.search(value) is None and not _looks_like_token(value)


def _looks_like_token(value: str) -> bool:
    lowered = value.casefold()
    if "authorization: bearer " in lowered or "authorization=bearer " in lowered:
        return True
    prefixes = ("sk-", "ghp_", "github_pat_", "xoxb-", "xoxp-")
    return any(prefix in lowered for prefix in prefixes)


def _valid_utc_timestamp(value: str) -> bool:
    if _UTC_TIMESTAMP_RE.fullmatch(value) is None:
        return False
    try:
        datetime.fromisoformat(value[:-1])
    except ValueError:
        return False
    return True


def _notify_corrupt_memory() -> None:
    try:
        warnings.warn(_CORRUPT_MEMORY_WARNING, RuntimeWarning, stacklevel=3)
    except Exception:  # noqa: BLE001 - caller warning filters must not block memory fallback.
        return


def _corrupt_outcome(path: Path) -> _LoadOutcome:
    try:
        quarantined = _isolate_corrupt(path)
    except (OSError, TypeError, ValueError):
        quarantined = False
    status = _QUARANTINED if quarantined else _UNREADABLE
    return _LoadOutcome(status, notify=True)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_bytes(path: Path) -> bytes:
    if not _path_is_safe(path) or _target_state(path) != "regular":
        raise _MemoryUnreadable
    try:
        with path.open("rb") as stream:
            metadata = os.fstat(stream.fileno())
            _validate_regular_metadata(metadata)
            raw = stream.read(_MAX_FILE_BYTES + 1)
            after = os.fstat(stream.fileno())
    except (OSError, ValueError):
        raise _MemoryUnreadable from None
    _validate_regular_metadata(after)
    if len(raw) > _MAX_FILE_BYTES:
        raise _MemoryTooLarge
    if metadata.st_size != after.st_size or metadata.st_mtime_ns != after.st_mtime_ns:
        raise _MemoryUnreadable
    return raw


def _atomic_write(path: Path, payload: dict[str, object]) -> None:
    temporary: Path | None = None
    try:
        if not _path_is_safe(path) or _target_state(path) not in {"missing", "regular"}:
            return
        encoded = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        parent = path.parent
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.tmp-", dir=parent)
        temporary = Path(temporary_name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if not _path_is_safe(path) or _target_state(path) not in {"missing", "regular"}:
            return
        os.replace(temporary, path)
        temporary = None
    except (OSError, ValueError, TypeError):
        return
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def _target_state(path: Path) -> str:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return _MISSING
    except (OSError, TypeError, ValueError):
        return _UNSAFE
    try:
        _validate_regular_metadata(metadata)
    except ValueError:
        return _UNSAFE
    return "regular"


def _validate_regular_metadata(metadata: os.stat_result) -> None:
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("memory target is not a regular file")
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if getattr(metadata, "st_file_attributes", 0) & reparse_flag:
        raise ValueError("memory target is a reparse point")


def _path_is_safe(path: Path) -> bool:
    try:
        absolute = Path(os.path.abspath(path))
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    if any(_protected_name(part) for part in absolute.parts):
        return False
    current = absolute
    while True:
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            if current.parent == current:
                return True
            current = current.parent
            continue
        except (OSError, TypeError, ValueError):
            return False
        if _is_reparse(metadata):
            return False
        if current.parent == current:
            return True
        current = current.parent


def _is_reparse(metadata: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & reparse_flag
    )


def _protected_name(name: str) -> bool:
    canonical = name.rstrip(" .").casefold()
    protected = {
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
        "credentials.json",
    }
    return canonical in protected or canonical.startswith(".env") or canonical.endswith(".egg-info")


def _isolate_corrupt(path: Path) -> bool:
    if not _path_is_safe(path) or _target_state(path) != "regular":
        return False
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    for index in range(1_000):
        suffix = f"-{index}" if index else ""
        candidate = path.with_name(f"{path.name}.corrupt-{stamp}{suffix}")
        try:
            os.link(path, candidate, follow_symlinks=False)
        except FileExistsError:
            continue
        except OSError:
            try:
                os.lstat(candidate)
            except FileNotFoundError:
                pass
            except OSError:
                return False
            else:
                continue
            try:
                os.rename(path, candidate)
            except OSError:
                return False
            return True
        try:
            path.unlink()
        except (OSError, ValueError):
            try:
                candidate.unlink()
            except (OSError, ValueError):
                pass
            return False
        return True
    return False
