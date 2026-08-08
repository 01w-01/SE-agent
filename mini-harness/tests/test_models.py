from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from fbw_harness.errors import ModelValidationError
from fbw_harness.models import (
    Action,
    ActionKind,
    ApprovalRequest,
    Feedback,
    FeedbackKind,
    Observation,
    PolicyContext,
    PolicyDecision,
    PolicyLevel,
    ProjectMemory,
    RawDecision,
    RawToolCall,
    RunEvent,
    RunRequest,
    RunResult,
    RunStatus,
    SessionState,
    TransactionRecord,
)
from fbw_harness.models import TestResult as HarnessTestResult
from fbw_harness.ports import (
    ApprovalProvider,
    CredentialStore,
    EventSink,
    LLMClient,
    LLMClientFactory,
)


@pytest.mark.parametrize("expected_sha256", [None, ""])
def test_edit_action_requires_non_empty_hash(expected_sha256: str | None) -> None:
    with pytest.raises(ModelValidationError, match="expected_sha256"):
        Action(
            kind=ActionKind.EDIT_FILE,
            path="src/a.py",
            expected_sha256=expected_sha256,
            old_text="x",
            new_text="y",
        )


@pytest.mark.parametrize(
    ("kind", "kwargs", "field"),
    [
        (ActionKind.READ_FILE, {"path": " "}, "path"),
        (
            ActionKind.EDIT_FILE,
            {
                "path": "src/a.py",
                "expected_sha256": " ",
                "old_text": "original",
                "new_text": "replacement",
            },
            "expected_sha256",
        ),
        (
            ActionKind.EDIT_FILE,
            {
                "path": "src/a.py",
                "expected_sha256": "0" * 64,
                "old_text": " ",
                "new_text": "replacement",
            },
            "old_text",
        ),
        (ActionKind.FINISH, {"reason": " "}, "reason"),
    ],
)
def test_action_non_empty_fields_allow_whitespace(
    kind: ActionKind, kwargs: dict[str, object], field: str
) -> None:
    action = Action(kind, **kwargs)  # type: ignore[arg-type]
    assert getattr(action, field) == " "


@pytest.mark.parametrize(
    ("kind", "kwargs", "field"),
    [
        (ActionKind.READ_FILE, {"path": 1}, "path"),
        (
            ActionKind.EDIT_FILE,
            {
                "path": "src/a.py",
                "expected_sha256": 1,
                "old_text": "original",
                "new_text": "replacement",
            },
            "expected_sha256",
        ),
        (
            ActionKind.EDIT_FILE,
            {
                "path": "src/a.py",
                "expected_sha256": "0" * 64,
                "old_text": 1,
                "new_text": "replacement",
            },
            "old_text",
        ),
        (ActionKind.FINISH, {"reason": 1}, "reason"),
    ],
)
def test_action_non_empty_fields_reject_non_strings(
    kind: ActionKind, kwargs: dict[str, object], field: str
) -> None:
    with pytest.raises(ModelValidationError, match=field):
        Action(kind, **kwargs)  # type: ignore[arg-type]


def test_run_request_rejects_blank_task() -> None:
    with pytest.raises(ModelValidationError, match="task"):
        RunRequest(Path("project"), " ", "https://example.test/v1", "model")


@pytest.mark.parametrize("field", ["api_key", "Authorization", "HEADERS", "file_content"])
def test_run_event_payload_rejects_secret_field(field: str) -> None:
    with pytest.raises(ModelValidationError, match="secret field"):
        RunEvent("run-1", "state", "start", {"meta": {field: "value"}})


def test_run_event_defensively_freezes_nested_payload() -> None:
    source = {
        "mapping": {"summary": "ok"},
        "sequence": [{"value": 1}],
        "set": {"a", "b"},
    }
    event = RunEvent("run-1", "state", "start", source)
    source["mapping"]["summary"] = "mutated"  # type: ignore[index]
    source["sequence"][0]["value"] = 2  # type: ignore[index]
    source["set"].add("c")  # type: ignore[union-attr]

    assert event.payload["mapping"]["summary"] == "ok"  # type: ignore[index]
    assert event.payload["sequence"] == ({"value": 1},)
    assert event.payload["set"] == frozenset({"a", "b"})
    with pytest.raises(TypeError):
        event.payload["late"] = "value"  # type: ignore[index]
    with pytest.raises(TypeError):
        event.payload["mapping"]["summary"] = "late"  # type: ignore[index]


def test_run_request_rejects_secret_and_freezes_overrides() -> None:
    source = {"nested": {"limit": 1}}
    request = RunRequest(
        Path("project"),
        "task",
        "https://example.test/v1",
        "model",
        config_overrides=source,
    )
    source["nested"]["limit"] = 2
    assert request.config_overrides["nested"]["limit"] == 1  # type: ignore[index]
    with pytest.raises(ModelValidationError, match="secret field"):
        RunRequest(
            Path("project"),
            "task",
            "https://example.test/v1",
            "model",
            config_overrides={"nested": {"HEADERS": "value"}},
        )


def test_recursive_container_is_rejected_without_recursion_error() -> None:
    recursive: dict[str, object] = {}
    recursive["self"] = recursive
    with pytest.raises(ModelValidationError, match="recursive"):
        RunEvent("run-1", "state", "start", recursive)


def test_shared_non_recursive_mapping_is_frozen_without_false_cycle_detection() -> None:
    shared = {"summary": "ok"}
    source = {"left": shared, "right": shared}
    event = RunEvent("run-1", "state", "start", source)
    shared["summary"] = "mutated"

    assert event.payload["left"]["summary"] == "ok"  # type: ignore[index]
    assert event.payload["right"]["summary"] == "ok"  # type: ignore[index]


def test_non_string_mapping_key_and_unsupported_object_are_rejected() -> None:
    with pytest.raises(ModelValidationError, match="string key"):
        RunEvent("run-1", "state", "start", {1: "value"})  # type: ignore[dict-item]
    with pytest.raises(ModelValidationError, match="unsupported"):
        RunEvent("run-1", "state", "start", {"value": object()})


@pytest.mark.parametrize(
    ("kind", "kwargs"),
    [
        (ActionKind.READ_FILE, {}),
        (ActionKind.CREATE_FILE, {"content": "x"}),
        (
            ActionKind.EDIT_FILE,
            {"expected_sha256": "0" * 64, "old_text": "x", "new_text": "y"},
        ),
    ],
)
@pytest.mark.parametrize("path", [None, ""])
def test_path_actions_require_non_empty_path(
    kind: ActionKind, kwargs: dict[str, object], path: str | None
) -> None:
    with pytest.raises(ModelValidationError, match="path"):
        Action(kind=kind, path=path, **kwargs)


@pytest.mark.parametrize(
    ("kwargs", "missing_field"),
    [
        ({"kind": ActionKind.CREATE_FILE, "path": "src/a.py"}, "content"),
        (
            {
                "kind": ActionKind.EDIT_FILE,
                "path": "src/a.py",
                "expected_sha256": "0" * 64,
                "new_text": "y",
            },
            "old_text",
        ),
        (
            {
                "kind": ActionKind.EDIT_FILE,
                "path": "src/a.py",
                "expected_sha256": "0" * 64,
                "old_text": "",
                "new_text": "y",
            },
            "old_text",
        ),
        (
            {
                "kind": ActionKind.EDIT_FILE,
                "path": "src/a.py",
                "expected_sha256": "0" * 64,
                "old_text": "x",
            },
            "new_text",
        ),
        ({"kind": ActionKind.FINISH}, "reason"),
    ],
)
def test_actions_reject_each_missing_required_field(
    kwargs: dict[str, object], missing_field: str
) -> None:
    with pytest.raises(ModelValidationError, match=missing_field):
        Action(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["task", "base_url", "model"])
def test_run_request_rejects_each_blank_required_string(field: str) -> None:
    kwargs = {
        "workspace": Path("project"),
        "task": "task",
        "base_url": "https://example.test/v1",
        "model": "model",
    }
    kwargs[field] = "\t"
    with pytest.raises(ModelValidationError, match=field):
        RunRequest(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["run_id", "kind", "stage"])
def test_run_event_rejects_each_blank_required_string(field: str) -> None:
    kwargs = {"run_id": "run-1", "kind": "state", "stage": "start"}
    kwargs[field] = "\n"
    with pytest.raises(ModelValidationError, match=field):
        RunEvent(**kwargs)


def test_fixed_result_models_require_all_contract_fields() -> None:
    with pytest.raises(TypeError):
        RawDecision()  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        RunResult(RunStatus.COMPLETED, "ok", 0)  # type: ignore[call-arg]


def test_approval_request_normalizes_sequence_fields() -> None:
    request = ApprovalRequest("R01", "reason", ["fact"], ["src/a.py"])  # type: ignore[arg-type]
    assert request.risk_facts == ("fact",)
    assert request.affected_paths == ("src/a.py",)


def test_tuple_and_frozenset_fields_are_normalized() -> None:
    raw_call = RawToolCall("act", "{}")
    decision = RawDecision([raw_call])  # type: ignore[arg-type]
    result = HarnessTestResult(True, 0, "", "", 0.1, failed_tests=["test_a"])  # type: ignore[arg-type]
    context = PolicyContext(["a.py"], 1, ["network"])  # type: ignore[arg-type]
    policy = PolicyDecision(PolicyLevel.CONFIRM, "R01", "reason", ["fact"])  # type: ignore[arg-type]
    feedback = Feedback(FeedbackKind.PASSED, True, 0, "ok", ["test_a"])  # type: ignore[arg-type]

    assert decision.tool_calls == (raw_call,)
    assert result.failed_tests == ("test_a",)
    assert context.dirty_paths == frozenset({"a.py"})
    assert context.dangerous_capabilities == frozenset({"network"})
    assert policy.risk_facts == ("fact",)
    assert feedback.failed_tests == ("test_a",)


def test_external_models_are_frozen_but_session_state_is_mutable() -> None:
    action = Action(ActionKind.LIST_FILES)
    with pytest.raises(FrozenInstanceError):
        action.reason = "changed"  # type: ignore[misc]

    state = SessionState("run-1")
    state.round_count += 1
    state.actions.append(("list_files", ""))
    assert state.round_count == 1
    assert state.actions == [("list_files", "")]


def test_session_state_normalizes_touched_files() -> None:
    state = SessionState("run-1", touched_files=["src/a.py"])  # type: ignore[arg-type]
    assert state.touched_files == ("src/a.py",)


@pytest.mark.parametrize(
    ("model", "expected_fields"),
    [
        (
            Action(ActionKind.LIST_FILES),
            ("kind", "path", "expected_sha256", "old_text", "new_text", "content", "reason"),
        ),
        (
            PolicyContext(),
            ("dirty_paths", "changed_line_count", "dangerous_capabilities"),
        ),
        (PolicyDecision(PolicyLevel.ALLOW, "R01", "reason"), ("level", "rule_id", "reason", "risk_facts")),
        (
            Observation("action", True, "ok"),
            ("kind", "success", "summary", "exit_code", "output_tail"),
        ),
        (
            Feedback(FeedbackKind.PASSED, True, 0, "ok"),
            (
                "kind",
                "passed",
                "exit_code",
                "summary",
                "failed_tests",
                "output_tail",
                "fingerprint",
            ),
        ),
        (
            HarnessTestResult(True, 0, "", "", 0.1),
            (
                "passed",
                "exit_code",
                "stdout",
                "stderr",
                "duration_seconds",
                "timed_out",
                "failed_tests",
            ),
        ),
        (
            TransactionRecord("src/a.py", True, None, Path("recovery")),
            (
                "relative_path",
                "originally_existed",
                "original_sha256",
                "recovery_path",
                "recovered",
            ),
        ),
        (
            ProjectMemory(),
            ("version", "project_notes", "last_success_summary", "updated_at"),
        ),
        (
            RunRequest(Path("project"), "task", "https://example.test/v1", "model"),
            ("workspace", "task", "base_url", "model", "config_path", "config_overrides"),
        ),
        (RunEvent("run-1", "state", "start"), ("run_id", "kind", "stage", "payload")),
        (
            ApprovalRequest("R01", "reason"),
            ("rule_id", "reason", "risk_facts", "affected_paths"),
        ),
        (RawToolCall("action", "{}"), ("name", "arguments")),
        (RawDecision(()), ("tool_calls", "content")),
        (
            RunResult(RunStatus.COMPLETED, "done", 0, 1, (), True, True, None),
            (
                "status",
                "stop_reason",
                "exit_code",
                "round_count",
                "touched_files",
                "last_test_passed",
                "rollback_complete",
                "recovery_path",
            ),
        ),
    ],
)
def test_fixed_models_have_exact_fields_and_are_frozen(
    model: object, expected_fields: tuple[str, ...]
) -> None:
    assert tuple(field.name for field in fields(model)) == expected_fields
    field_name = expected_fields[0]
    with pytest.raises(FrozenInstanceError):
        setattr(model, field_name, getattr(model, field_name))


def test_session_state_has_exact_fields_and_is_the_only_mutable_model() -> None:
    state = SessionState("run-1")
    assert tuple(field.name for field in fields(state)) == (
        "run_id",
        "state",
        "round_count",
        "invalid_count",
        "repeat_count",
        "actions",
        "last_feedback",
        "last_test_passed",
        "touched_files",
        "fingerprints",
    )
    state.run_id = "run-2"
    assert state.run_id == "run-2"


def test_model_enums_have_stable_string_values() -> None:
    assert [kind.value for kind in ActionKind] == [
        "list_files",
        "read_file",
        "create_file",
        "edit_file",
        "finish",
    ]
    assert [level.value for level in PolicyLevel] == ["allow", "confirm", "deny"]
    assert FeedbackKind.UNKNOWN_TEST_FAILURE.value == "unknown_test_failure"
    assert RunStatus.ROLLBACK_INCOMPLETE.value == "rollback_incomplete"


class FakeEventSink:
    def emit(self, event: RunEvent) -> None:
        del event


class FakeApprovalProvider:
    def confirm(self, request: ApprovalRequest) -> bool:
        del request
        return True


class FakeCredentialStore:
    def get(self) -> str | None:
        return "value"

    def set(self, value: str) -> None:
        del value

    def clear(self) -> bool:
        return True


class FakeLLMClient:
    def decide(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
    ) -> RawDecision:
        del messages, tools
        return RawDecision(())


class FakeLLMClientFactory:
    def create(self, *, base_url: str, model: str, api_key: str) -> LLMClient:
        del base_url, model, api_key
        return FakeLLMClient()


def test_runtime_protocols_accept_structural_fakes() -> None:
    assert isinstance(FakeEventSink(), EventSink)
    assert isinstance(FakeApprovalProvider(), ApprovalProvider)
    assert isinstance(FakeCredentialStore(), CredentialStore)
    assert isinstance(FakeLLMClient(), LLMClient)
    assert isinstance(FakeLLMClientFactory(), LLMClientFactory)
