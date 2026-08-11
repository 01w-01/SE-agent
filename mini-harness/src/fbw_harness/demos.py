from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .app import ApplicationService
from .mock_llm import MockLLMCall, ScriptedMockLLM
from .models import (
    Action,
    PolicyDecision,
    PolicyLevel,
    RawDecision,
    RawToolCall,
    RunEvent,
    RunRequest,
    RunResult,
)
from .ports import LLMClient

_FIXTURE_ROOT = Path(__file__).parents[2] / "tests" / "fixtures" / "clamp_project"
_INITIAL_FRAGMENT = "min(max(value, lower), upper)"
_WRONG_FRAGMENT = "min(max(value, upper), lower)"


@dataclass(frozen=True, slots=True)
class DemoResult:
    exit_code: int
    run_result: RunResult
    llm_calls: tuple[MockLLMCall, ...]
    original_file_text: str
    workspace_file_text: str
    file_tool_calls: int
    policy_denied: bool
    policy_decisions: tuple[PolicyDecision, ...]
    events: tuple[RunEvent, ...]
    llm_factory_type: type[object]


class _StaticCredentialStore:
    def get(self) -> str:
        return "demo-credential"

    def set(self, value: str) -> None:
        raise AssertionError("demos never set credentials")

    def clear(self) -> bool:
        raise AssertionError("demos never clear credentials")


class _MockFactory:
    def __init__(self, client: ScriptedMockLLM) -> None:
        self.client = client

    def create(
        self, *, base_url: str, model: str, api_key: str, max_retries: int | None = None
    ) -> LLMClient:
        return self.client


class _RecordingEvents:
    def __init__(self) -> None:
        self.events: list[RunEvent] = []

    def emit(self, event: RunEvent) -> None:
        self.events.append(event)


class _RunTrace:
    def __init__(self) -> None:
        self.policy_decisions: list[PolicyDecision] = []
        self.file_actions: list[Action] = []


class _AlwaysApprove:
    def confirm(self, _request: object) -> bool:
        return True


def run_demo(name: str) -> DemoResult:
    if name not in {"guardrail", "feedback", "no-progress"}:
        raise ValueError("unknown demo")
    with tempfile.TemporaryDirectory(prefix="fbw-harness-demo-") as temporary:
        workspace = Path(temporary) / "project"
        shutil.copytree(_FIXTURE_ROOT, workspace)
        original = (workspace / "clamp.py").read_text(encoding="utf-8")
        decisions = _decisions(name, original)
        llm = ScriptedMockLLM(decisions)
        factory = _MockFactory(llm)
        events = _RecordingEvents()
        trace = _RunTrace()
        result = _run_application(
            workspace=workspace,
            name=name,
            llm_factory=factory,
            events=events,
            trace=trace,
        )
        current = (workspace / "clamp.py").read_text(encoding="utf-8")
        policy_decisions = tuple(trace.policy_decisions)
        run_events = tuple(events.events)
        demo = DemoResult(
            exit_code=0,
            run_result=result,
            llm_calls=llm.calls,
            original_file_text=original,
            workspace_file_text=current,
            file_tool_calls=len(trace.file_actions),
            policy_denied=_guardrail_was_denied(policy_decisions),
            policy_decisions=policy_decisions,
            events=run_events,
            llm_factory_type=type(factory),
        )
        _verify(name, demo)
        return demo


def _run_application(
    *,
    workspace: Path,
    name: str,
    llm_factory: _MockFactory,
    events: _RecordingEvents,
    trace: _RunTrace,
) -> RunResult:
    from . import app as application

    policy_base = application.PolicyEngine
    dispatcher_base = application.ToolDispatcher

    class RecordingPolicyEngine(policy_base):
        def evaluate(self, action: Action, context: object) -> PolicyDecision:
            decision = super().evaluate(action, context)  # type: ignore[arg-type]
            trace.policy_decisions.append(decision)
            return decision

    class RecordingToolDispatcher(dispatcher_base):
        def execute(self, action: Action):  # type: ignore[no-untyped-def]
            trace.file_actions.append(action)
            return super().execute(action)

    application.PolicyEngine = RecordingPolicyEngine
    application.ToolDispatcher = RecordingToolDispatcher
    try:
        service = ApplicationService(
            credential_store=_StaticCredentialStore(),
            llm_factory=llm_factory,
            event_sink=events,
            approval_provider=_AlwaysApprove(),
        )
        return service.run(
            RunRequest(
                workspace=workspace,
                task=f"run deterministic {name} demonstration",
                base_url="https://mock.invalid/v1",
                model="scripted-mock",
                config_overrides={"max_rounds": 6, "repeat_limit": 2, "pytest_args": ["-q"]},
            )
        )
    finally:
        application.PolicyEngine = policy_base
        application.ToolDispatcher = dispatcher_base


def _decisions(name: str, original: str) -> tuple[RawDecision, ...]:
    if name == "guardrail":
        denied = _call("read_file", {"path": "../outside.txt"})
        return (denied, denied)
    wrong = original.replace(_INITIAL_FRAGMENT, _WRONG_FRAGMENT)
    original_hash = _sha256(original)
    wrong_hash = _sha256(wrong)
    wrong_edit = _call(
        "edit_file",
        {
            "path": "clamp.py",
            "expected_sha256": original_hash,
            "old_text": _INITIAL_FRAGMENT,
            "new_text": _WRONG_FRAGMENT,
        },
    )
    if name == "feedback":
        return (
            wrong_edit,
            _call(
                "edit_file",
                {
                    "path": "clamp.py",
                    "expected_sha256": wrong_hash,
                    "old_text": _WRONG_FRAGMENT,
                    "new_text": _INITIAL_FRAGMENT,
                },
            ),
            _call("finish", {"reason": "tests now pass"}),
        )
    repeated_error = _call(
        "edit_file",
        {
            "path": "clamp.py",
            "expected_sha256": wrong_hash,
            "old_text": _WRONG_FRAGMENT,
            "new_text": _WRONG_FRAGMENT,
        },
    )
    return (wrong_edit, repeated_error, repeated_error)


def _call(name: str, arguments: dict[str, str]) -> RawDecision:
    return RawDecision((RawToolCall(name, json.dumps(arguments, sort_keys=True)),))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _verify(name: str, demo: DemoResult) -> None:
    if name == "guardrail":
        valid = (
            demo.policy_denied
            and len(demo.policy_decisions) == 2
            and demo.file_tool_calls == 0
            and not any(event.stage == "executing" for event in demo.events)
        )
    elif name == "feedback":
        valid = demo.run_result.last_test_passed is True and demo.run_result.exit_code == 0
    else:
        valid = (
            demo.run_result.stop_reason == "no_progress"
            and demo.run_result.rollback_complete
            and demo.workspace_file_text == demo.original_file_text
        )
    if not valid:
        raise RuntimeError(f"{name} demo invariant failed")


def _guardrail_was_denied(decisions: tuple[PolicyDecision, ...]) -> bool:
    return bool(decisions) and all(
        decision.level is PolicyLevel.DENY and decision.rule_id == "DENY_PATH_ESCAPE"
        for decision in decisions
    )
