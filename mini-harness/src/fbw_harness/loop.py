from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import replace
from pathlib import Path

from .config import HarnessConfig
from .context import ContextBuilder
from .feedback import FeedbackEngine, fingerprint
from .models import (
    Action,
    ActionKind,
    Feedback,
    FeedbackKind,
    Observation,
    PolicyContext,
    PolicyLevel,
    ProjectMemory,
    RunEvent,
    RunRequest,
    RunResult,
    RunStatus,
    SessionState,
)
from .parser import ActionParseError, ActionParser, build_action_tools
from .policy import PolicyEngine, authorize
from .ports import ApprovalProvider, EventSink, LLMClient
from .testing import TestRunner
from .transactions import FileTransaction, RollbackReport
from .workspace import FileSnapshot, Workspace

_MAX_CONTEXT_FILES = 100
_MAX_CONTEXT_OBSERVATIONS = 100
_RUN_ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
_RUN_ID_ERROR = "run_id is invalid"


class ToolDispatcher:
    """Dispatch only the five declared actions to controlled components."""

    def __init__(self, workspace: Workspace, transaction: FileTransaction) -> None:
        self._workspace = workspace
        self._transaction = transaction

    def execute(self, action: Action) -> Observation:
        try:
            return self._execute(action)
        except Exception:  # noqa: BLE001 - tool failures cross the loop as fixed observations.
            return Observation(
                kind=action.kind.value,
                success=False,
                summary="Tool execution failed.",
            )

    def _execute(self, action: Action) -> Observation:
        if action.kind is ActionKind.LIST_FILES:
            paths = self._workspace.list_files()
            return Observation(
                kind=action.kind.value,
                success=True,
                summary="Files listed.",
                output_tail=json.dumps(paths, ensure_ascii=False),
            )
        if action.kind is ActionKind.READ_FILE:
            assert action.path is not None
            snapshot = self._workspace.read_file(action.path)
            return Observation(
                kind=action.kind.value,
                success=True,
                summary="File read.",
                output_tail=snapshot.text,
            )
        if action.kind is ActionKind.CREATE_FILE:
            assert action.path is not None and action.content is not None
            snapshot = self._transaction.create_file(action.path, action.content)
            return _write_observation(action.kind, snapshot)
        if action.kind is ActionKind.EDIT_FILE:
            assert action.path is not None
            assert action.expected_sha256 is not None
            assert action.old_text is not None and action.new_text is not None
            snapshot = self._transaction.edit_file(
                action.path,
                action.expected_sha256,
                action.old_text,
                action.new_text,
            )
            return _write_observation(action.kind, snapshot)
        if action.kind is ActionKind.FINISH:
            return Observation(
                kind=action.kind.value,
                success=True,
                summary="Finish requested.",
            )
        raise AssertionError("unhandled action")

    def context_files(self) -> tuple[FileSnapshot, ...]:
        paths = self._workspace.list_files()[:_MAX_CONTEXT_FILES]
        return tuple(self._workspace.read_file(path) for path in paths)

    @property
    def touched_paths(self) -> tuple[str, ...]:
        return self._transaction.touched_paths

    def commit(self) -> None:
        self._transaction.commit()

    def rollback(self) -> RollbackReport:
        return self._transaction.rollback()


class AgentLoop:
    def __init__(
        self,
        *,
        llm: LLMClient,
        parser: ActionParser,
        context_builder: ContextBuilder,
        policy: PolicyEngine,
        dispatcher: ToolDispatcher,
        test_runner: TestRunner,
        feedback_engine: FeedbackEngine,
        event_sink: EventSink,
        approval_provider: ApprovalProvider,
        config: HarnessConfig,
        recovery_path: Path,
        memory: ProjectMemory | None = None,
        run_id: str | None = None,
    ) -> None:
        self._llm = llm
        self._parser = parser
        self._context_builder = context_builder
        self._policy = policy
        self._dispatcher = dispatcher
        self._test_runner = test_runner
        self._feedback_engine = feedback_engine
        self._event_sink = event_sink
        self._approval_provider = approval_provider
        self._config = config
        self._recovery_path = Path(os.path.abspath(Path(recovery_path)))
        self._memory = memory
        self._run_id = _validated_run_id(run_id)

    def run(self, request: RunRequest) -> RunResult:
        state = SessionState(run_id=self._run_id)
        observations: list[Observation] = []
        try:
            self._transition(state, RunStatus.INITIALIZING)
            return self._run_state_machine(request, state, observations)
        except KeyboardInterrupt:
            return self._failure(state, "interrupted")
        except Exception:  # noqa: BLE001 - the loop owns every injected component boundary.
            return self._failure(state, "internal_error")

    def _run_state_machine(
        self,
        request: RunRequest,
        state: SessionState,
        observations: list[Observation],
    ) -> RunResult:
        while state.round_count < self._config.max_rounds:
            self._transition(state, RunStatus.REQUESTING_ACTION)
            try:
                messages = self._context_builder.build(
                    request=request,
                    observations=observations,
                    feedback=state.last_feedback,
                    memory=self._memory,
                    files=self._dispatcher.context_files(),
                )
            except KeyboardInterrupt:
                raise
            except Exception:  # noqa: BLE001 - context inputs are normalized at this boundary.
                return self._failure(state, "context_error")
            state.round_count += 1
            try:
                decision = self._llm.decide(messages, build_action_tools())
            except KeyboardInterrupt:
                raise
            except Exception:  # noqa: BLE001 - LLM errors must not escape with provider details.
                return self._failure(state, "api_failure")
            self._transition(state, RunStatus.VALIDATING_ACTION)
            try:
                action = self._parser.parse(decision)
            except ActionParseError:
                state.invalid_count += 1
                state.repeat_count = 0
                state.actions.clear()
                state.last_feedback = _fixed_feedback(
                    FeedbackKind.PARSE_ERROR,
                    "Model decision did not match the action protocol.",
                )
                self._transition(state, RunStatus.FEEDBACK)
                if state.invalid_count >= 3:
                    return self._failure(state, "format_error_limit")
                continue
            state.invalid_count = 0
            policy_decision = self._policy.evaluate(action, _policy_context(action))

            if policy_decision.level is PolicyLevel.DENY:
                state.last_feedback = self._feedback_engine.from_policy(policy_decision)
                self._transition(state, RunStatus.FEEDBACK)
                if self._has_no_progress(state, action):
                    return self._failure(state, "no_progress")
                continue

            if policy_decision.level is PolicyLevel.CONFIRM:
                self._transition(state, RunStatus.WAITING_APPROVAL)
                affected_paths = (action.path,) if action.path is not None else ()
                if not authorize(
                    policy_decision,
                    self._approval_provider,
                    affected_paths=affected_paths,
                ):
                    state.last_feedback = _fixed_feedback(
                        FeedbackKind.POLICY_DENIED,
                        "Policy confirmation was declined.",
                    )
                    self._transition(state, RunStatus.FEEDBACK)
                    return self._failure(state, "user_rejected")

            if action.kind in {ActionKind.CREATE_FILE, ActionKind.EDIT_FILE}:
                state.last_test_passed = None
            self._transition(state, RunStatus.EXECUTING)
            try:
                observation = self._dispatcher.execute(action)
            except KeyboardInterrupt:
                raise
            except Exception:  # noqa: BLE001 - injected tool failures become fixed observations.
                observation = Observation(
                    kind=action.kind.value,
                    success=False,
                    summary="Tool execution failed.",
                )
            observations.append(observation)
            if len(observations) > _MAX_CONTEXT_OBSERVATIONS:
                del observations[:-_MAX_CONTEXT_OBSERVATIONS]

            if not observation.success:
                state.last_feedback = self._feedback_engine.from_tool(observation)
                self._transition(state, RunStatus.FEEDBACK)
                if self._has_no_progress(state, action):
                    return self._failure(state, "no_progress")
                continue

            if action.kind in {ActionKind.CREATE_FILE, ActionKind.EDIT_FILE}:
                self._transition(state, RunStatus.VERIFYING)
                test_result = self._test_runner.run(request.workspace)
                state.last_test_passed = test_result.passed
                state.last_feedback = self._feedback_engine.from_test(test_result)
                self._transition(state, RunStatus.FEEDBACK)
                if test_result.timed_out:
                    return self._failure(state, "pytest_timeout")
                if self._has_no_progress(state, action):
                    return self._failure(state, "no_progress")
                continue

            if action.kind is ActionKind.FINISH:
                if state.last_test_passed is True:
                    touched_files = self._dispatcher.touched_paths
                    try:
                        self._dispatcher.commit()
                    except KeyboardInterrupt:
                        return self._commit_failure(state, "interrupted", touched_files)
                    except Exception:  # noqa: BLE001 - commit errors retain recovery material.
                        return self._commit_failure(state, "internal_error", touched_files)
                    self._safe_transition(state, RunStatus.COMPLETED)
                    return RunResult(
                        status=RunStatus.COMPLETED,
                        stop_reason="completed",
                        exit_code=0,
                        round_count=state.round_count,
                        touched_files=touched_files,
                        last_test_passed=True,
                        rollback_complete=True,
                        recovery_path=None,
                    )
                state.last_feedback = _fixed_feedback(
                    FeedbackKind.UNKNOWN_TEST_FAILURE,
                    "Finish requires the latest pytest run to pass.",
                )
            self._transition(state, RunStatus.FEEDBACK)
            if self._has_no_progress(state, action):
                return self._failure(state, "no_progress")

        return self._failure(state, "max_rounds")

    def _failure(self, state: SessionState, reason: str) -> RunResult:
        self._safe_transition(state, RunStatus.ROLLING_BACK)
        try:
            report = self._dispatcher.rollback()
        except BaseException:  # noqa: BLE001 - recovery failure must still return exit semantics.
            report = RollbackReport(complete=False)
        status = RunStatus.FAILED if report.complete else RunStatus.ROLLBACK_INCOMPLETE
        self._safe_transition(state, status)
        recovery_path = None
        if not report.complete:
            recovery_path = report.recovery_root or self._recovery_path
        return RunResult(
            status=status,
            stop_reason=reason,
            exit_code=1 if report.complete else 3,
            round_count=state.round_count,
            touched_files=self._dispatcher.touched_paths,
            last_test_passed=state.last_test_passed,
            rollback_complete=report.complete,
            recovery_path=recovery_path,
        )

    def _commit_failure(
        self,
        state: SessionState,
        reason: str,
        touched_files: tuple[str, ...],
    ) -> RunResult:
        self._safe_transition(state, RunStatus.ROLLBACK_INCOMPLETE)
        return RunResult(
            status=RunStatus.ROLLBACK_INCOMPLETE,
            stop_reason=reason,
            exit_code=3,
            round_count=state.round_count,
            touched_files=touched_files,
            last_test_passed=state.last_test_passed,
            rollback_complete=False,
            recovery_path=self._recovery_path,
        )

    def _has_no_progress(self, state: SessionState, action: Action) -> bool:
        feedback_fingerprint = (
            state.last_feedback.fingerprint if state.last_feedback is not None else ""
        )
        current = (_action_signature(action), feedback_fingerprint)
        if state.actions and state.actions[-1] == current:
            state.repeat_count += 1
        else:
            state.repeat_count = 1
        state.actions[:] = [current]
        return state.repeat_count >= self._config.repeat_limit

    def _transition(self, state: SessionState, status: RunStatus) -> None:
        state.state = status
        try:
            self._event_sink.emit(
                RunEvent(
                    run_id=state.run_id,
                    kind="state",
                    stage=status.value,
                    payload={"round_count": state.round_count},
                )
            )
        except Exception:  # noqa: BLE001 - ordinary telemetry failures are non-fatal.
            return

    def _safe_transition(self, state: SessionState, status: RunStatus) -> None:
        try:
            self._transition(state, status)
        except BaseException:  # noqa: BLE001 - cleanup/committed states must finish safely.
            return


def _write_observation(kind: ActionKind, snapshot: FileSnapshot) -> Observation:
    return Observation(
        kind=kind.value,
        success=True,
        summary="File written.",
        output_tail=json.dumps(
            {"path": snapshot.path, "sha256": snapshot.sha256},
            ensure_ascii=False,
            sort_keys=True,
        ),
    )


def _policy_context(action: Action) -> PolicyContext:
    if action.kind is ActionKind.CREATE_FILE:
        changed = _line_count(action.content)
    elif action.kind is ActionKind.EDIT_FILE:
        changed = _line_count(action.old_text) + _line_count(action.new_text)
    else:
        changed = 0
    return PolicyContext(dirty_paths=frozenset(), changed_line_count=changed)


def _line_count(value: str | None) -> int:
    if not value:
        return 0
    return len(value.splitlines()) or 1


def _fixed_feedback(kind: FeedbackKind, summary: str) -> Feedback:
    feedback = Feedback(
        kind=kind,
        passed=None,
        exit_code=None,
        summary=summary,
    )
    return replace(feedback, fingerprint=fingerprint(feedback))


def _action_signature(action: Action) -> str:
    digest = hashlib.sha256()
    for value in (
        action.kind.value,
        action.path,
        action.expected_sha256,
        action.old_text,
        action.new_text,
        action.content,
        action.reason,
    ):
        encoded = (value or "").encode("utf-8", errors="replace")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _validated_run_id(value: object) -> str:
    if value is None:
        return uuid.uuid4().hex
    if type(value) is not str or _RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(_RUN_ID_ERROR) from None
    return value
