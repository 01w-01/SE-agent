from __future__ import annotations

import json

import pytest

from fbw_harness import app as application
from fbw_harness.loop import AgentLoop
from fbw_harness.models import PolicyDecision, PolicyLevel, RawDecision, RawToolCall


def test_guardrail_demo_denies_escape_without_file_tool_call() -> None:
    # Break caught: an escaping model action reaches the controlled file dispatcher.
    from fbw_harness.demos import run_demo

    result = run_demo("guardrail")

    assert result.exit_code == 0
    assert result.run_result.stop_reason == "no_progress"
    assert result.run_result.rollback_complete is True
    assert result.file_tool_calls == 0
    assert result.policy_denied is True
    assert [decision.level for decision in result.policy_decisions] == [
        PolicyLevel.DENY,
        PolicyLevel.DENY,
    ]
    assert [decision.rule_id for decision in result.policy_decisions] == [
        "DENY_PATH_ESCAPE",
        "DENY_PATH_ESCAPE",
    ]
    assert not any(event.stage == "executing" for event in result.events)


def test_guardrail_demo_rejects_a_policy_bypass_after_real_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Break caught: guardrail success is inferred from its name rather than real deny/dispatch outcomes.
    from fbw_harness import demos

    original_policy = application.PolicyEngine
    original_dispatcher = application.ToolDispatcher

    class AllowingPolicy(original_policy):
        def evaluate(self, action, context):  # type: ignore[no-untyped-def]
            return PolicyDecision(PolicyLevel.ALLOW, "TEST_ALLOW", "test policy bypass")

    dispatcher_calls: list[object] = []

    class RecordingDispatcher(original_dispatcher):
        def execute(self, action):  # type: ignore[no-untyped-def]
            dispatcher_calls.append(action)
            return super().execute(action)

    monkeypatch.setattr(application, "PolicyEngine", AllowingPolicy)
    monkeypatch.setattr(application, "ToolDispatcher", RecordingDispatcher)

    with pytest.raises(RuntimeError, match="guardrail demo invariant failed"):
        demos.run_demo("guardrail")

    assert len(dispatcher_calls) == 2


def test_feedback_demo_passes_after_second_request_receives_latest_feedback() -> None:
    # Break caught: test feedback is omitted from the follow-up LLM request, so correction cannot occur.
    from fbw_harness.demos import run_demo

    result = run_demo("feedback")

    assert result.exit_code == 0
    assert result.run_result.last_test_passed is True
    assert result.run_result.round_count == 3
    latest_feedback = json.loads(result.llm_calls[1].messages[-1]["content"])
    assert latest_feedback["section"] == "latest_feedback"
    assert latest_feedback["feedback"]["passed"] is False


def test_no_progress_demo_rolls_back_original_file_after_repeated_error() -> None:
    # Break caught: repeated failing actions do not stop or leave the first mutation behind.
    from fbw_harness.demos import run_demo

    result = run_demo("no-progress")

    assert result.exit_code == 0
    assert result.run_result.stop_reason == "no_progress"
    assert result.run_result.rollback_complete is True
    assert result.workspace_file_text == result.original_file_text


def test_mock_demos_and_real_cli_share_application_and_agent_loop(monkeypatch) -> None:
    # Break caught: demos construct a parallel loop instead of the production composition root.
    from fbw_harness import cli, demos

    captured: list[tuple[type[object], type[object]]] = []
    original = demos.ApplicationService

    class RecordingService(original):
        def __init__(self, **kwargs: object) -> None:
            captured.append((type(self), AgentLoop))
            super().__init__(**kwargs)

    monkeypatch.setattr(demos, "ApplicationService", RecordingService)
    demos.run_demo("guardrail")

    assert captured == [(RecordingService, AgentLoop)]
    assert cli.ApplicationService is original


def test_cli_and_demo_construct_the_same_loop_with_different_factories(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    # Break caught: a demo can silently bypass the real composition root or reuse the real LLM factory.
    from fbw_harness import cli, demos
    from fbw_harness.mock_llm import ScriptedMockLLM

    service_inits: list[tuple[type[object], type[object]]] = []
    loop_types: list[type[object]] = []
    original_service_init = application.ApplicationService.__init__
    original_loop = application.AgentLoop

    def record_service_init(self, **kwargs):  # type: ignore[no-untyped-def]
        service_inits.append((type(self), type(kwargs["llm_factory"])))
        original_service_init(self, **kwargs)

    class RecordingAgentLoop(original_loop):
        def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
            loop_types.append(type(self))
            super().__init__(**kwargs)

    class CliFactory:
        def __init__(self) -> None:
            finish = RawDecision((RawToolCall("finish", '{"reason":"stop"}'),))
            self.client = ScriptedMockLLM((finish, finish))

        def create(self, **kwargs):  # type: ignore[no-untyped-def]
            return self.client

    class CredentialStore:
        def get(self) -> str:
            return "test-credential"

    monkeypatch.setattr(application.ApplicationService, "__init__", record_service_init)
    monkeypatch.setattr(application, "AgentLoop", RecordingAgentLoop)
    monkeypatch.setattr(cli, "OpenAIClientFactory", CliFactory)

    assert (
        cli.main(
            [
                "run",
                "--workspace",
                str(tmp_path),
                "--task",
                "composition check",
                "--base-url",
                "https://example.test/v1",
                "--model",
                "real-factory-model",
            ],
            credential_store=CredentialStore(),
        )
        == 1
    )
    demo = demos.run_demo("guardrail")

    assert cli.ApplicationService is demos.ApplicationService is application.ApplicationService
    assert service_inits == [
        (application.ApplicationService, CliFactory),
        (application.ApplicationService, demos._MockFactory),
    ]
    assert loop_types == [RecordingAgentLoop, RecordingAgentLoop]
    assert demo.llm_factory_type is demos._MockFactory
