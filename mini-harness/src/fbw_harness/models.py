from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType

from .errors import ModelValidationError

_SECRET_FIELDS = frozenset({"api_key", "authorization", "headers", "file_content"})
type _FrozenValue = (
    None
    | bool
    | int
    | float
    | str
    | tuple["_FrozenValue", ...]
    | frozenset["_FrozenValue"]
    | Mapping[str, "_FrozenValue"]
)


def _freeze(value: object, *, reject_secrets: bool, active: set[int]) -> _FrozenValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            raise ModelValidationError("recursive container is not supported")
        active.add(identity)
        try:
            frozen: dict[str, _FrozenValue] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ModelValidationError("mapping requires a string key")
                if reject_secrets and key.casefold() in _SECRET_FIELDS:
                    raise ModelValidationError(f"secret field is not allowed: {key}")
                frozen[key] = _freeze(item, reject_secrets=reject_secrets, active=active)
            return MappingProxyType(frozen)
        finally:
            active.remove(identity)

    if isinstance(value, (list, tuple, set, frozenset)):
        identity = id(value)
        if identity in active:
            raise ModelValidationError("recursive container is not supported")
        active.add(identity)
        try:
            items = (_freeze(item, reject_secrets=reject_secrets, active=active) for item in value)
            if isinstance(value, (set, frozenset)):
                try:
                    return frozenset(items)
                except TypeError as error:
                    raise ModelValidationError("unsupported unhashable set item") from error
            return tuple(items)
        finally:
            active.remove(identity)

    raise ModelValidationError(f"unsupported value type: {type(value).__name__}")


def _freeze_mapping(value: Mapping[str, object], *, reject_secrets: bool) -> Mapping[str, object]:
    frozen = _freeze(value, reject_secrets=reject_secrets, active=set())
    if not isinstance(frozen, Mapping):
        raise ModelValidationError("value must be a mapping")
    return frozen


def _require_non_blank(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ModelValidationError(f"{field_name} must be a non-blank string")


def _require_non_empty(value: object, field_name: str) -> None:
    if not isinstance(value, str) or value == "":
        raise ModelValidationError(f"{field_name} must be a non-empty string")


class ActionKind(str, Enum):
    LIST_FILES = "list_files"
    READ_FILE = "read_file"
    CREATE_FILE = "create_file"
    EDIT_FILE = "edit_file"
    FINISH = "finish"


class PolicyLevel(str, Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


class FeedbackKind(str, Enum):
    PASSED = "passed"
    ASSERTION_FAILURE = "assertion_failure"
    COLLECTION_FAILURE = "collection_failure"
    SYNTAX_ERROR = "syntax_error"
    IMPORT_ERROR = "import_error"
    TIMEOUT = "timeout"
    POLICY_DENIED = "policy_denied"
    TOOL_ERROR = "tool_error"
    PARSE_ERROR = "parse_error"
    UNKNOWN_TEST_FAILURE = "unknown_test_failure"


class RunStatus(str, Enum):
    INITIALIZING = "initializing"
    REQUESTING_ACTION = "requesting_action"
    VALIDATING_ACTION = "validating_action"
    WAITING_APPROVAL = "waiting_approval"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    FEEDBACK = "feedback"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLING_BACK = "rolling_back"
    ROLLBACK_INCOMPLETE = "rollback_incomplete"


@dataclass(frozen=True, slots=True)
class Action:
    kind: ActionKind
    path: str | None = None
    expected_sha256: str | None = None
    old_text: str | None = None
    new_text: str | None = None
    content: str | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if self.kind in {ActionKind.READ_FILE, ActionKind.CREATE_FILE, ActionKind.EDIT_FILE}:
            _require_non_empty(self.path, "path")
        if self.kind is ActionKind.CREATE_FILE and self.content is None:
            raise ModelValidationError("content is required for create_file")
        if self.kind is ActionKind.EDIT_FILE:
            _require_non_empty(self.expected_sha256, "expected_sha256")
            _require_non_empty(self.old_text, "old_text")
            if self.new_text is None:
                raise ModelValidationError("new_text is required for edit_file")
        if self.kind is ActionKind.FINISH:
            _require_non_empty(self.reason, "reason")


@dataclass(frozen=True, slots=True)
class PolicyContext:
    dirty_paths: frozenset[str] = frozenset()
    changed_line_count: int = 0
    dangerous_capabilities: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "dirty_paths", frozenset(self.dirty_paths))
        object.__setattr__(
            self, "dangerous_capabilities", frozenset(self.dangerous_capabilities)
        )


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    level: PolicyLevel
    rule_id: str
    reason: str
    risk_facts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "risk_facts", tuple(self.risk_facts))


@dataclass(frozen=True, slots=True)
class Observation:
    kind: str
    success: bool
    summary: str
    exit_code: int | None = None
    output_tail: str = ""


@dataclass(frozen=True, slots=True)
class Feedback:
    kind: FeedbackKind
    passed: bool | None
    exit_code: int | None
    summary: str
    failed_tests: tuple[str, ...] = ()
    output_tail: str = ""
    fingerprint: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "failed_tests", tuple(self.failed_tests))


@dataclass(frozen=True, slots=True)
class TestResult:
    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    failed_tests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "failed_tests", tuple(self.failed_tests))


@dataclass(slots=True)
class SessionState:
    run_id: str
    state: RunStatus = RunStatus.INITIALIZING
    round_count: int = 0
    invalid_count: int = 0
    repeat_count: int = 0
    actions: list[tuple[str, str]] = field(default_factory=list)
    last_feedback: Feedback | None = None
    last_test_passed: bool | None = None
    touched_files: tuple[str, ...] = ()
    fingerprints: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.touched_files = tuple(self.touched_files)


@dataclass(frozen=True, slots=True)
class TransactionRecord:
    relative_path: str
    originally_existed: bool
    original_sha256: str | None
    recovery_path: Path
    recovered: bool = False


@dataclass(frozen=True, slots=True)
class ProjectMemory:
    version: int = 1
    project_notes: str = ""
    last_success_summary: str = ""
    updated_at: str = ""


@dataclass(frozen=True, slots=True)
class RunRequest:
    workspace: Path
    task: str
    base_url: str
    model: str
    config_path: Path | None = None
    config_overrides: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_blank(self.task, "task")
        _require_non_blank(self.base_url, "base_url")
        _require_non_blank(self.model, "model")
        object.__setattr__(self, "workspace", Path(self.workspace))
        if self.config_path is not None:
            object.__setattr__(self, "config_path", Path(self.config_path))
        object.__setattr__(
            self,
            "config_overrides",
            _freeze_mapping(self.config_overrides, reject_secrets=True),
        )


@dataclass(frozen=True, slots=True)
class RunEvent:
    run_id: str
    kind: str
    stage: str
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_blank(self.run_id, "run_id")
        _require_non_blank(self.kind, "kind")
        _require_non_blank(self.stage, "stage")
        object.__setattr__(self, "payload", _freeze_mapping(self.payload, reject_secrets=True))


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    rule_id: str
    reason: str
    risk_facts: tuple[str, ...] = ()
    affected_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "risk_facts", tuple(self.risk_facts))
        object.__setattr__(self, "affected_paths", tuple(self.affected_paths))


@dataclass(frozen=True, slots=True)
class RawToolCall:
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class RawDecision:
    tool_calls: tuple[RawToolCall, ...]
    content: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))


@dataclass(frozen=True, slots=True)
class RunResult:
    status: RunStatus
    stop_reason: str
    exit_code: int
    round_count: int
    touched_files: tuple[str, ...]
    last_test_passed: bool | None
    rollback_complete: bool
    recovery_path: Path | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "touched_files", tuple(self.touched_files))
