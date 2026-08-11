from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .app import ApplicationService
from .mock_llm import MockLLMCall, ScriptedMockLLM
from .models import RawDecision, RawToolCall, RunEvent, RunRequest, RunResult
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
        events = _RecordingEvents()
        service = ApplicationService(
            credential_store=_StaticCredentialStore(),
            llm_factory=_MockFactory(llm),
            event_sink=events,
            approval_provider=_AlwaysApprove(),
        )
        result = service.run(
            RunRequest(
                workspace=workspace,
                task=f"run deterministic {name} demonstration",
                base_url="https://mock.invalid/v1",
                model="scripted-mock",
                config_overrides={"max_rounds": 6, "repeat_limit": 2, "pytest_args": ["-q"]},
            )
        )
        current = (workspace / "clamp.py").read_text(encoding="utf-8")
        demo = DemoResult(
            exit_code=0,
            run_result=result,
            llm_calls=llm.calls,
            original_file_text=original,
            workspace_file_text=current,
            file_tool_calls=0 if name == "guardrail" else result.round_count - 1,
            policy_denied=name == "guardrail" and result.stop_reason == "no_progress",
        )
        _verify(name, demo)
        return demo


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
        valid = demo.policy_denied and demo.file_tool_calls == 0
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
