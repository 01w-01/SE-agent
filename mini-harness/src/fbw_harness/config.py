from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path

from fbw_harness.errors import InputError
from fbw_harness.models import RunRequest


@dataclass(frozen=True, slots=True)
class HarnessConfig:
    max_rounds: int = 6
    api_retries: int = 2
    pytest_timeout_seconds: int = 60
    repeat_limit: int = 2
    file_size_limit_bytes: int = 262_144
    normal_change_line_limit: int = 200
    output_tail_chars: int = 12_000
    pytest_args: tuple[str, ...] = ("-q",)
    jsonl_log: Path | None = None
    memory_enabled: bool = False
    memory_path: Path | None = None


_INTEGER_FIELDS = frozenset(
    {
        "max_rounds",
        "api_retries",
        "pytest_timeout_seconds",
        "repeat_limit",
        "file_size_limit_bytes",
        "normal_change_line_limit",
        "output_tail_chars",
    }
)
_PATH_FIELDS = frozenset({"jsonl_log", "memory_path"})
_ALLOWED_FIELDS = frozenset(field.name for field in fields(HarnessConfig))
_FORBIDDEN_FIELD_PARTS = ("api_key", "authorization", "secret", "headers", "file_content")
_UNSAFE_PYTEST_ARGUMENT_CHARS = (";", "|", "&", "\n", "\r")


def load_config(request: RunRequest, *, user_config: Path | None) -> HarnessConfig:
    """Load declared, non-secret configuration with deterministic precedence."""
    cli_values = _validate_values(request.config_overrides, "CLI")
    user_values = _load_file(user_config, "user")
    project_values = _load_file(request.config_path, "project")

    values = {field.name: getattr(HarnessConfig(), field.name) for field in fields(HarnessConfig)}
    values.update(user_values)
    values.update(project_values)
    values.update(cli_values)
    return HarnessConfig(**values)


def _load_file(path: Path | None, source: str) -> dict[str, object]:
    if path is None:
        return {}
    try:
        values = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise InputError(f"Invalid {source} configuration field config_file") from error
    return _validate_values(values, source)


def _validate_values(values: Mapping[str, object], source: str) -> dict[str, object]:
    validated: dict[str, object] = {}
    for name, value in values.items():
        _validate_field_name(name, source)
        validated[name] = _validate_value(name, value, source)
    return validated


def _validate_field_name(name: str, source: str) -> None:
    lowered_name = name.lower()
    if any(part in lowered_name for part in _FORBIDDEN_FIELD_PARTS):
        raise InputError(f"{source} configuration field {name} is secret and not allowed")
    if name not in _ALLOWED_FIELDS:
        raise InputError(f"{source} configuration field {name} is not allowed")


def _validate_value(name: str, value: object, source: str) -> object:
    if name in _INTEGER_FIELDS:
        if type(value) is not int or value <= 0:
            raise InputError(f"{source} configuration field {name} must be a positive integer")
        return value
    if name == "memory_enabled":
        if type(value) is not bool:
            raise InputError(f"{source} configuration field {name} must be a boolean")
        return value
    if name in _PATH_FIELDS:
        if value is None:
            return None
        if not isinstance(value, (str, Path)):
            raise InputError(f"{source} configuration field {name} must be a path")
        return Path(value)
    if name == "pytest_args":
        return _validate_pytest_args(value, source)
    raise AssertionError(f"Unhandled configuration field: {name}")


def _validate_pytest_args(value: object, source: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not all(type(item) is str for item in value):
        raise InputError(f"{source} configuration field pytest_args must be a list of strings")
    for argument in value:
        if argument.startswith(("@", "--rootdir", "-c")) or any(
            character in argument for character in _UNSAFE_PYTEST_ARGUMENT_CHARS
        ):
            raise InputError(f"{source} configuration field pytest_args contains an unsafe argument")
    return tuple(value)
