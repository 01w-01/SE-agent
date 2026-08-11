from __future__ import annotations

import json

from fbw_harness.loop import AgentLoop


def test_guardrail_demo_denies_escape_without_file_tool_call() -> None:
    # Break caught: an escaping model action reaches the controlled file dispatcher.
    from fbw_harness.demos import run_demo

    result = run_demo("guardrail")

    assert result.exit_code == 0
    assert result.run_result.stop_reason == "no_progress"
    assert result.run_result.rollback_complete is True
    assert result.file_tool_calls == 0
    assert result.policy_denied is True


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
