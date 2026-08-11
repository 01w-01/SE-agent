from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import fbw_harness.app as app_module
from fbw_harness.app import ApplicationService
from fbw_harness.config import HarnessConfig
from fbw_harness.context import ContextBuilder
from fbw_harness.feedback import FeedbackEngine
from fbw_harness.llm import LLMDecisionError
from fbw_harness.loop import AgentLoop, ToolDispatcher
from fbw_harness.memory import JsonProjectMemoryStore
from fbw_harness.mock_llm import ScriptedMockLLM
from fbw_harness.models import (
    Action,
    ActionKind,
    ApprovalRequest,
    RawDecision,
    RawToolCall,
    RunEvent,
    RunRequest,
    RunResult,
    RunStatus,
)
from fbw_harness.parser import ActionParser
from fbw_harness.policy import PolicyEngine
from fbw_harness.testing import TestRunner as HarnessTestRunner
from fbw_harness.transactions import FileTransaction, RollbackReport
from fbw_harness.workspace import Workspace


class RecordingEventSink:
    def __init__(self) -> None:
        self.events: list[RunEvent] = []

    def emit(self, event: RunEvent) -> None:
        self.events.append(event)


class FixedApprovalProvider:
    def __init__(self, approved: bool) -> None:
        self.approved = approved
        self.requests: list[ApprovalRequest] = []

    def confirm(self, request: ApprovalRequest) -> bool:
        self.requests.append(request)
        return self.approved


class CountingToolDispatcher(ToolDispatcher):
    def __init__(self, workspace: Workspace, transaction: FileTransaction) -> None:
        super().__init__(workspace, transaction)
        self.call_count = 0

    def execute(self, action: Action):  # type: ignore[no-untyped-def]
        self.call_count += 1
        return super().execute(action)


class ExplodingTestRunner:
    def run(self, workspace: Path | Workspace):  # type: ignore[no-untyped-def]
        raise RuntimeError("injected test runner failure")


class InterruptingTestRunner:
    def run(self, workspace: Path | Workspace):  # type: ignore[no-untyped-def]
        raise KeyboardInterrupt


class ExplodingEventSink:
    def emit(self, event: RunEvent) -> None:
        raise RuntimeError("injected event sink failure")


class FixedCredentialStore:
    def __init__(self, value: str | None) -> None:
        self.value = value

    def get(self) -> str | None:
        return self.value

    def set(self, value: str) -> None:
        self.value = value

    def clear(self) -> bool:
        self.value = None
        return True


class RecordingLLMFactory:
    def __init__(self, decisions: list[RawDecision]) -> None:
        self.decisions = decisions
        self.calls: list[dict[str, str]] = []

    def create(self, *, base_url: str, model: str, api_key: str) -> ScriptedMockLLM:
        self.calls.append({"base_url": base_url, "model": model, "api_key": api_key})
        return ScriptedMockLLM(self.decisions)


def tool_decision(name: str, arguments: dict[str, object]) -> RawDecision:
    return RawDecision((RawToolCall(name, json.dumps(arguments)),))


def runtime_api_key() -> str:
    parts = ("runtime", "_credential", "_value")
    return "".join(parts)


def make_loop(
    root: Path,
    decisions: list[RawDecision],
    *,
    config: HarnessConfig | None = None,
    approval_provider: FixedApprovalProvider | None = None,
    test_runner: object | None = None,
    event_sink: object | None = None,
) -> tuple[AgentLoop, ScriptedMockLLM, CountingToolDispatcher, FileTransaction]:
    selected_config = config or HarnessConfig()
    workspace = Workspace(root, selected_config.file_size_limit_bytes)
    recovery_path = root.parent / "recovery"
    transaction = FileTransaction(workspace, recovery_path)
    llm = ScriptedMockLLM(decisions)
    dispatcher = CountingToolDispatcher(workspace, transaction)
    loop = AgentLoop(
        llm=llm,
        parser=ActionParser(),
        context_builder=ContextBuilder(max_chars=12_000),
        policy=PolicyEngine(workspace, selected_config.normal_change_line_limit),
        dispatcher=dispatcher,
        test_runner=(
            HarnessTestRunner(selected_config, known_secrets=())
            if test_runner is None
            else test_runner  # type: ignore[arg-type]
        ),
        feedback_engine=FeedbackEngine(selected_config.output_tail_chars, known_secrets=()),
        event_sink=(RecordingEventSink() if event_sink is None else event_sink),  # type: ignore[arg-type]
        approval_provider=approval_provider or FixedApprovalProvider(True),
        config=selected_config,
        recovery_path=recovery_path,
    )
    return loop, llm, dispatcher, transaction


def write_clamp_project(root: Path) -> tuple[str, str, str]:
    root.mkdir()
    initial = "def clamp(value, lower, upper):\n    return value\n"
    wrong = "def clamp(value, lower, upper):\n    return max(value, lower)\n"
    correct = "def clamp(value, lower, upper):\n    return max(lower, min(value, upper))\n"
    (root / "clamp.py").write_bytes(initial.encode())
    (root / "test_clamp.py").write_bytes(
        b"from clamp import clamp\n\n"
        b"def test_bounds():\n"
        b"    assert clamp(-1, 0, 10) == 0\n"
        b"    assert clamp(11, 0, 10) == 10\n"
    )
    return initial, wrong, correct


def test_dispatcher_delegates_declared_actions_to_controlled_components(tmp_path: Path) -> None:
    """Catches dispatch bypassing Workspace/FileTransaction or omitting an action."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "existing.txt").write_bytes(b"old\n")
    workspace = Workspace(root)
    transaction = FileTransaction(workspace, tmp_path / "recovery")
    dispatcher = ToolDispatcher(workspace, transaction)

    listed = dispatcher.execute(Action(ActionKind.LIST_FILES))
    read = dispatcher.execute(Action(ActionKind.READ_FILE, path="existing.txt"))
    created = dispatcher.execute(
        Action(ActionKind.CREATE_FILE, path="created.txt", content="created\n")
    )
    before = workspace.read_file("existing.txt")
    edited = dispatcher.execute(
        Action(
            ActionKind.EDIT_FILE,
            path="existing.txt",
            expected_sha256=before.sha256,
            old_text="old",
            new_text="new",
        )
    )
    finished = dispatcher.execute(Action(ActionKind.FINISH, reason="done"))

    assert (listed.success, read.success, created.success, edited.success, finished.success) == (
        True,
        True,
        True,
        True,
        True,
    )
    assert "existing.txt" in listed.output_tail
    assert read.output_tail == "old\n"
    assert (root / "created.txt").read_text(encoding="utf-8") == "created\n"
    assert (root / "existing.txt").read_text(encoding="utf-8") == "new\n"
    assert transaction.touched_paths == ("created.txt", "existing.txt")


@pytest.mark.parametrize(
    ("path", "approved", "stop_reason"),
    [
        (".env", True, "max_rounds"),
        ("package.json", False, "user_rejected"),
    ],
)
def test_governance_prevents_denied_or_unapproved_tool_execution(
    tmp_path: Path, path: str, approved: bool, stop_reason: str
) -> None:
    """Catches policy-blocked actions reaching the dispatcher before authorization."""
    root = tmp_path / "project"
    root.mkdir()
    config = HarnessConfig(max_rounds=1)
    approval = FixedApprovalProvider(approved)
    loop, _, dispatcher, transaction = make_loop(
        root,
        [tool_decision("create_file", {"path": path, "content": "unsafe\n"})],
        config=config,
        approval_provider=approval,
    )

    result = loop.run(
        RunRequest(root, "make a controlled change", "https://example.test/v1", "mock")
    )

    assert result.status is RunStatus.FAILED
    assert result.stop_reason == stop_reason
    assert dispatcher.call_count == 0
    assert transaction.touched_paths == ()
    assert not (root / path).exists()
    assert len(approval.requests) == (0 if path == ".env" else 1)


def test_failed_verification_drives_correction_and_gates_finish(tmp_path: Path) -> None:
    """Catches writes skipping pytest or premature finish bypassing the latest-test gate."""
    root = tmp_path / "project"
    initial, wrong, correct = write_clamp_project(root)
    initial_hash = hashlib.sha256(initial.encode()).hexdigest()
    wrong_hash = hashlib.sha256(wrong.encode()).hexdigest()
    decisions = [
        tool_decision(
            "edit_file",
            {
                "path": "clamp.py",
                "expected_sha256": initial_hash,
                "old_text": "return value",
                "new_text": "return max(value, lower)",
            },
        ),
        tool_decision("finish", {"reason": "premature"}),
        tool_decision(
            "edit_file",
            {
                "path": "clamp.py",
                "expected_sha256": wrong_hash,
                "old_text": "return max(value, lower)",
                "new_text": "return max(lower, min(value, upper))",
            },
        ),
        tool_decision("finish", {"reason": "tests passed"}),
    ]
    loop, llm, dispatcher, _ = make_loop(root, decisions)

    result = loop.run(RunRequest(root, "fix clamp", "https://example.test/v1", "mock"))

    assert result.status is RunStatus.COMPLETED
    assert result.stop_reason == "completed"
    assert result.last_test_passed is True
    assert result.round_count == 4
    assert dispatcher.call_count == 4
    assert (root / "clamp.py").read_text(encoding="utf-8") == correct
    first_feedback_context = json.dumps(llm.calls[1].messages, ensure_ascii=False)
    finish_gate_context = json.dumps(llm.calls[2].messages, ensure_ascii=False)
    assert "assertion_failure" in first_feedback_context
    assert "Finish requires the latest pytest run to pass." in finish_gate_context


def test_repeated_action_and_feedback_stops_for_no_progress(tmp_path: Path) -> None:
    """Catches identical failed actions consuming every round instead of stopping safely."""
    root = tmp_path / "project"
    initial, _, _ = write_clamp_project(root)
    initial_hash = hashlib.sha256(initial.encode()).hexdigest()
    invalid = tool_decision(
        "edit_file",
        {
            "path": "clamp.py",
            "expected_sha256": initial_hash,
            "old_text": "missing text",
            "new_text": "bad",
        },
    )
    loop, _, dispatcher, _ = make_loop(root, [invalid, invalid])

    result = loop.run(RunRequest(root, "fix clamp", "https://example.test/v1", "mock"))

    assert result.status is RunStatus.FAILED
    assert result.stop_reason == "no_progress"
    assert result.rollback_complete is True
    assert result.round_count == 2
    assert dispatcher.call_count == 2
    assert (root / "clamp.py").read_text(encoding="utf-8") == initial


def test_three_consecutive_parse_errors_stop_without_dispatch(tmp_path: Path) -> None:
    """Catches malformed model decisions escaping or reaching a tool boundary."""
    root = tmp_path / "project"
    root.mkdir()
    malformed = RawDecision(())
    loop, llm, dispatcher, _ = make_loop(root, [malformed, malformed, malformed])

    result = loop.run(RunRequest(root, "inspect", "https://example.test/v1", "mock"))

    assert result.status is RunStatus.FAILED
    assert result.stop_reason == "format_error_limit"
    assert result.round_count == 3
    assert len(llm.calls) == 3
    assert dispatcher.call_count == 0


def test_max_rounds_stops_and_rolls_back(tmp_path: Path) -> None:
    """Catches a non-writing loop requesting decisions beyond its configured bound."""
    root = tmp_path / "project"
    root.mkdir()
    decision = tool_decision("list_files", {})
    config = HarnessConfig(max_rounds=2, repeat_limit=3)
    loop, llm, dispatcher, _ = make_loop(root, [decision, decision], config=config)

    result = loop.run(RunRequest(root, "inspect", "https://example.test/v1", "mock"))

    assert result.status is RunStatus.FAILED
    assert result.stop_reason == "max_rounds"
    assert result.round_count == 2
    assert len(llm.calls) == 2
    assert dispatcher.call_count == 2
    assert result.rollback_complete is True


def test_context_file_selection_is_bounded_before_builder(tmp_path: Path) -> None:
    """Catches a valid 101-file workspace being rejected by ContextBuilder's input bound."""
    root = tmp_path / "project"
    root.mkdir()
    for index in range(101):
        (root / f"file_{index:03d}.txt").write_bytes(b"safe\n")
    config = HarnessConfig(max_rounds=1)
    decision = tool_decision("list_files", {})
    loop, llm, dispatcher, _ = make_loop(root, [decision], config=config)

    result = loop.run(RunRequest(root, "inspect", "https://example.test/v1", "mock"))

    assert result.stop_reason == "max_rounds"
    assert len(llm.calls) == 1
    assert dispatcher.call_count == 1


def test_observation_history_is_bounded_before_builder(tmp_path: Path) -> None:
    """Catches a valid long run failing when observation history exceeds 100 entries."""
    root = tmp_path / "project"
    root.mkdir()
    rounds = 102
    decision = tool_decision("list_files", {})
    config = HarnessConfig(max_rounds=rounds, repeat_limit=rounds + 1)
    loop, llm, dispatcher, _ = make_loop(root, [decision] * rounds, config=config)

    result = loop.run(RunRequest(root, "inspect", "https://example.test/v1", "mock"))

    assert result.stop_reason == "max_rounds"
    assert len(llm.calls) == rounds
    assert dispatcher.call_count == rounds


def test_pytest_timeout_stops_and_removes_created_file(tmp_path: Path) -> None:
    """Catches timed-out verification continuing decisions or retaining a write."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "test_slow.py").write_bytes(b"import time\n\ndef test_slow():\n    time.sleep(5)\n")
    config = HarnessConfig(pytest_timeout_seconds=1)
    decision = tool_decision("create_file", {"path": "created.py", "content": "value = 1\n"})
    loop, _, _, _ = make_loop(root, [decision], config=config)

    result = loop.run(RunRequest(root, "add value", "https://example.test/v1", "mock"))

    assert result.status is RunStatus.FAILED
    assert result.stop_reason == "pytest_timeout"
    assert result.last_test_passed is False
    assert result.rollback_complete is True
    assert not (root / "created.py").exists()


def test_api_failure_is_normalized_and_rolled_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches LLM transport failures escaping the state machine."""
    root = tmp_path / "project"
    root.mkdir()
    loop, llm, dispatcher, _ = make_loop(root, [])

    def fail_decision(*_args: object, **_kwargs: object) -> RawDecision:
        raise LLMDecisionError("injected API failure")

    monkeypatch.setattr(llm, "decide", fail_decision)
    result = loop.run(RunRequest(root, "inspect", "https://example.test/v1", "mock"))

    assert result.status is RunStatus.FAILED
    assert result.stop_reason == "api_failure"
    assert result.round_count == 1
    assert dispatcher.call_count == 0
    assert result.rollback_complete is True


def test_internal_test_runner_failure_rolls_back_write(tmp_path: Path) -> None:
    """Catches internal verification errors escaping after a transactional mutation."""
    root = tmp_path / "project"
    root.mkdir()
    decision = tool_decision("create_file", {"path": "created.py", "content": "value = 1\n"})
    loop, _, _, _ = make_loop(root, [decision], test_runner=ExplodingTestRunner())

    result = loop.run(RunRequest(root, "add value", "https://example.test/v1", "mock"))

    assert result.status is RunStatus.FAILED
    assert result.stop_reason == "internal_error"
    assert result.rollback_complete is True
    assert not (root / "created.py").exists()


def test_commit_cleanup_failure_returns_recovery_path_without_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches commit-started cleanup failure attempting a forbidden rollback."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "test_ok.py").write_bytes(b"def test_ok():\n    assert True\n")
    decisions = [
        tool_decision("create_file", {"path": "created.py", "content": "value = 1\n"}),
        tool_decision("finish", {"reason": "done"}),
    ]
    sink = RecordingEventSink()
    loop, _, _, transaction = make_loop(root, decisions, event_sink=sink)
    recovery_path = root.parent / "recovery"

    monkeypatch.setattr(transaction, "_remove_recovery_tree", lambda: False)
    result = loop.run(RunRequest(root, "add value", "https://example.test/v1", "mock"))

    assert result.status is RunStatus.ROLLBACK_INCOMPLETE
    assert result.stop_reason == "internal_error"
    assert result.exit_code == 3
    assert result.rollback_complete is False
    assert result.recovery_path == recovery_path
    assert (root / "created.py").exists()
    assert any(recovery_path.iterdir())
    assert "rolling_back" not in (event.stage for event in sink.events)
    assert sink.events[-1].stage == "rollback_incomplete"


def test_rollback_exception_uses_explicit_recovery_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches rollback exceptions returning exit three without recovery material location."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "test_ok.py").write_bytes(b"def test_ok():\n    assert True\n")
    config = HarnessConfig(max_rounds=1)
    decision = tool_decision("create_file", {"path": "created.py", "content": "value = 1\n"})
    sink = RecordingEventSink()
    loop, _, _, transaction = make_loop(root, [decision], config=config, event_sink=sink)
    recovery_path = root.parent / "recovery"

    def fail_rollback() -> RollbackReport:
        raise RuntimeError("injected rollback failure")

    monkeypatch.setattr(transaction, "rollback", fail_rollback)
    result = loop.run(RunRequest(root, "add value", "https://example.test/v1", "mock"))

    assert result.status is RunStatus.ROLLBACK_INCOMPLETE
    assert result.stop_reason == "max_rounds"
    assert result.exit_code == 3
    assert result.rollback_complete is False
    assert result.recovery_path == recovery_path
    assert (root / "created.py").exists()
    assert tuple(event.stage for event in sink.events)[-2:] == (
        "rolling_back",
        "rollback_incomplete",
    )


def test_incomplete_rollback_returns_exit_three_and_recovery_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches incomplete recovery being reported as an ordinary failure."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "test_ok.py").write_bytes(b"def test_ok():\n    assert True\n")
    config = HarnessConfig(max_rounds=1)
    decision = tool_decision("create_file", {"path": "created.py", "content": "value = 1\n"})
    loop, _, _, transaction = make_loop(root, [decision], config=config)

    def incomplete_rollback() -> RollbackReport:
        recovery_path = next((root.parent / "recovery").iterdir())
        return RollbackReport(False, transaction.touched_paths, recovery_path)

    monkeypatch.setattr(transaction, "rollback", incomplete_rollback)
    result = loop.run(RunRequest(root, "add value", "https://example.test/v1", "mock"))

    assert result.status is RunStatus.ROLLBACK_INCOMPLETE
    assert result.stop_reason == "max_rounds"
    assert result.exit_code == 3
    assert result.rollback_complete is False
    assert result.recovery_path is not None
    assert result.recovery_path.is_dir()


def test_application_injects_one_known_secrets_tuple_and_run_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches app wiring divergent secret sets or recovery/run identifiers."""
    root = tmp_path / "project"
    root.mkdir()
    runtime_key = runtime_api_key()
    factory = RecordingLLMFactory([])
    captured: dict[str, object] = {}
    recovery_calls: list[str] = []

    class CapturingLoop:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def run(self, request: RunRequest) -> RunResult:
            return RunResult(RunStatus.COMPLETED, "completed", 0, 0, (), True, True, None)

    def recovery_root(run_id: str) -> Path:
        recovery_calls.append(run_id)
        return tmp_path / "recovery" / run_id

    monkeypatch.setattr(app_module, "AgentLoop", CapturingLoop)
    service = ApplicationService(
        credential_store=FixedCredentialStore(runtime_key),
        llm_factory=factory,
        event_sink=RecordingEventSink(),
        approval_provider=FixedApprovalProvider(True),
        recovery_root_factory=recovery_root,
    )

    result = service.run(RunRequest(root, "inspect", "https://example.test/v1", "model-name"))

    assert result.status is RunStatus.COMPLETED
    assert factory.calls == [
        {
            "base_url": "https://example.test/v1",
            "model": "model-name",
            "api_key": runtime_key,
        }
    ]
    runner_secrets = captured["test_runner"]._known_secrets  # type: ignore[attr-defined]
    feedback_secrets = captured["feedback_engine"]._known_secrets  # type: ignore[attr-defined]
    assert runner_secrets is feedback_secrets
    assert runner_secrets == (runtime_key,)
    assert captured["memory"] is None
    assert captured["run_id"] == recovery_calls[0]
    assert captured["recovery_path"] == tmp_path / "recovery" / recovery_calls[0]


def test_application_saves_only_fixed_success_memory_summary(tmp_path: Path) -> None:
    """Catches successful app runs omitting memory or persisting sensitive request data."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "test_ok.py").write_bytes(b"def test_ok():\n    assert True\n")
    memory_path = tmp_path / "memory.json"
    task_text = "add private customer feature"
    runtime_key = runtime_api_key()
    factory = RecordingLLMFactory(
        [
            tool_decision("create_file", {"path": "created.py", "content": "value = 1\n"}),
            tool_decision("finish", {"reason": "done"}),
        ]
    )
    service = ApplicationService(
        credential_store=FixedCredentialStore(runtime_key),
        llm_factory=factory,
        event_sink=RecordingEventSink(),
        approval_provider=FixedApprovalProvider(True),
        recovery_root_factory=lambda run_id: tmp_path / "recovery" / run_id,
    )
    request = RunRequest(
        root,
        task_text,
        "https://example.test/v1",
        "model-name",
        config_overrides={
            "memory_enabled": True,
            "memory_path": str(memory_path),
        },
    )

    result = service.run(request)

    assert result.status is RunStatus.COMPLETED
    saved = JsonProjectMemoryStore(memory_path, enabled=True).load()
    assert saved is not None
    assert saved.last_success_summary == "status=completed; rounds=2; files=1"
    serialized = memory_path.read_text(encoding="utf-8")
    assert task_text not in serialized
    assert runtime_key not in serialized
    assert str(root) not in serialized


def test_application_failure_does_not_replace_existing_memory(tmp_path: Path) -> None:
    """Catches failed app runs overwriting the last successful project memory."""
    root = tmp_path / "project"
    root.mkdir()
    memory_path = tmp_path / "memory.json"
    store = JsonProjectMemoryStore(memory_path, enabled=True)
    store.save_success("prior success")
    before = memory_path.read_bytes()
    runtime_key = runtime_api_key()
    malformed = RawDecision(())
    service = ApplicationService(
        credential_store=FixedCredentialStore(runtime_key),
        llm_factory=RecordingLLMFactory([malformed, malformed, malformed]),
        event_sink=RecordingEventSink(),
        approval_provider=FixedApprovalProvider(True),
        recovery_root_factory=lambda run_id: tmp_path / "recovery" / run_id,
    )
    request = RunRequest(
        root,
        "inspect",
        "https://example.test/v1",
        "model-name",
        config_overrides={
            "memory_enabled": True,
            "memory_path": str(memory_path),
        },
    )

    result = service.run(request)

    assert result.status is RunStatus.FAILED
    assert result.stop_reason == "format_error_limit"
    assert memory_path.read_bytes() == before


@pytest.mark.parametrize("memory_state", ["missing", "corrupt"])
def test_application_memory_unavailable_falls_back_to_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    memory_state: str,
) -> None:
    """Catches absent or corrupt optional memory preventing app composition."""
    root = tmp_path / "project"
    root.mkdir()
    memory_path = tmp_path / "memory.json"
    if memory_state == "corrupt":
        memory_path.write_bytes(b"not-json")
    runtime_key = runtime_api_key()
    captured: dict[str, object] = {}

    class CapturingLoop:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def run(self, request: RunRequest) -> RunResult:
            return RunResult(RunStatus.FAILED, "max_rounds", 1, 0, (), None, True, None)

    monkeypatch.setattr(app_module, "AgentLoop", CapturingLoop)
    service = ApplicationService(
        credential_store=FixedCredentialStore(runtime_key),
        llm_factory=RecordingLLMFactory([]),
        event_sink=RecordingEventSink(),
        approval_provider=FixedApprovalProvider(True),
        recovery_root_factory=lambda run_id: tmp_path / "recovery" / run_id,
    )
    request = RunRequest(
        root,
        "inspect",
        "https://example.test/v1",
        "model-name",
        config_overrides={
            "memory_enabled": True,
            "memory_path": str(memory_path),
        },
    )

    if memory_state == "corrupt":
        with pytest.warns(RuntimeWarning):
            result = service.run(request)
    else:
        result = service.run(request)

    assert result.status is RunStatus.FAILED
    assert captured["memory"] is None


def test_keyboard_interrupt_rolls_back_and_emits_sanitized_state_order(tmp_path: Path) -> None:
    """Catches Ctrl+C escaping after a write or leaking request/file data through events."""
    root = tmp_path / "project"
    root.mkdir()
    runtime_marker = runtime_api_key()
    file_body = f"value = {runtime_marker!r}\n"
    sink = RecordingEventSink()
    decision = tool_decision("create_file", {"path": "private_module.py", "content": file_body})
    loop, _, _, _ = make_loop(
        root,
        [decision],
        test_runner=InterruptingTestRunner(),
        event_sink=sink,
    )

    result = loop.run(RunRequest(root, f"task {runtime_marker}", "https://example.test/v1", "mock"))

    assert result.status is RunStatus.FAILED
    assert result.stop_reason == "interrupted"
    assert result.exit_code == 1
    assert result.rollback_complete is True
    assert result.recovery_path is None
    assert not (root / "private_module.py").exists()
    assert tuple(event.stage for event in sink.events) == (
        "initializing",
        "requesting_action",
        "validating_action",
        "executing",
        "verifying",
        "rolling_back",
        "failed",
    )
    serialized_events = json.dumps(
        [
            {
                "run_id": event.run_id,
                "kind": event.kind,
                "stage": event.stage,
                "payload": dict(event.payload),
            }
            for event in sink.events
        ],
        ensure_ascii=False,
    )
    assert runtime_marker not in serialized_events
    assert file_body not in serialized_events
    assert str(root) not in serialized_events
    assert all(set(event.payload) == {"round_count"} for event in sink.events)


def test_injected_tool_exception_becomes_feedback_then_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a tool exception leaking details or bypassing feedback and rollback."""
    root = tmp_path / "project"
    root.mkdir()
    decisions = [
        tool_decision("create_file", {"path": "created.py", "content": "value = 1\n"}),
        tool_decision("finish", {"reason": "stop"}),
    ]
    config = HarnessConfig(max_rounds=2)
    loop, llm, dispatcher, _ = make_loop(root, decisions, config=config)
    real_execute = dispatcher.execute

    def execute_then_fail(action: Action):  # type: ignore[no-untyped-def]
        observation = real_execute(action)
        if action.kind is ActionKind.CREATE_FILE:
            assert observation.success
            raise RuntimeError("injected tool detail")
        return observation

    monkeypatch.setattr(dispatcher, "execute", execute_then_fail)
    result = loop.run(RunRequest(root, "add value", "https://example.test/v1", "mock"))

    assert result.status is RunStatus.FAILED
    assert result.stop_reason == "max_rounds"
    assert result.rollback_complete is True
    assert not (root / "created.py").exists()
    feedback_context = json.dumps(llm.calls[1].messages, ensure_ascii=False)
    assert "tool_error" in feedback_context
    assert "injected tool detail" not in feedback_context


def test_later_write_invalidates_prior_passing_test_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches finish committing a write whose post-write observation failed."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "test_ok.py").write_bytes(b"def test_ok():\n    assert True\n")
    decisions = [
        tool_decision("create_file", {"path": "verified.py", "content": "value = 1\n"}),
        tool_decision("create_file", {"path": "unverified.py", "content": "value = 2\n"}),
        tool_decision("finish", {"reason": "unsafe finish"}),
    ]
    config = HarnessConfig(max_rounds=3)
    loop, _, dispatcher, _ = make_loop(root, decisions, config=config)
    real_execute = dispatcher.execute

    def fail_after_second_write(action: Action):  # type: ignore[no-untyped-def]
        observation = real_execute(action)
        if action.path == "unverified.py":
            assert observation.success
            raise RuntimeError("injected post-write observation failure")
        return observation

    monkeypatch.setattr(dispatcher, "execute", fail_after_second_write)
    result = loop.run(RunRequest(root, "add values", "https://example.test/v1", "mock"))

    assert result.status is RunStatus.FAILED
    assert result.stop_reason == "max_rounds"
    assert result.last_test_passed is None
    assert result.rollback_complete is True
    assert not (root / "verified.py").exists()
    assert not (root / "unverified.py").exists()


def test_context_failure_has_fixed_stop_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches context construction errors being mislabeled as API or leaking outward."""
    root = tmp_path / "project"
    root.mkdir()
    loop, _, dispatcher, _ = make_loop(root, [])

    def fail_context(**_kwargs: object) -> list[dict[str, object]]:
        raise RuntimeError("injected context detail")

    monkeypatch.setattr(loop._context_builder, "build", fail_context)
    result = loop.run(RunRequest(root, "inspect", "https://example.test/v1", "mock"))

    assert result.status is RunStatus.FAILED
    assert result.stop_reason == "context_error"
    assert result.round_count == 0
    assert dispatcher.call_count == 0
    assert result.rollback_complete is True


def test_event_sink_failure_does_not_change_success(tmp_path: Path) -> None:
    """Catches telemetry failures altering commit or completion semantics."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "test_ok.py").write_bytes(b"def test_ok():\n    assert True\n")
    decisions = [
        tool_decision("create_file", {"path": "created.py", "content": "value = 1\n"}),
        tool_decision("finish", {"reason": "done"}),
    ]
    loop, _, _, _ = make_loop(root, decisions, event_sink=ExplodingEventSink())

    result = loop.run(RunRequest(root, "add value", "https://example.test/v1", "mock"))

    assert result.status is RunStatus.COMPLETED
    assert result.exit_code == 0
    assert (root / "created.py").read_text(encoding="utf-8") == "value = 1\n"
