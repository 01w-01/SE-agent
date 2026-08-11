from __future__ import annotations

from pathlib import Path

import pytest

from fbw_harness.models import RunEvent, RunRequest, RunResult, RunStatus


class FakeApplication:
    def __init__(self) -> None:
        self.requests: list[RunRequest] = []

    def run(self, request: RunRequest) -> RunResult:
        self.requests.append(request)
        return RunResult(
            status=RunStatus.COMPLETED,
            stop_reason="success",
            exit_code=0,
            round_count=1,
            touched_files=("clamp.py",),
            last_test_passed=True,
            rollback_complete=True,
            recovery_path=None,
        )


class FakeCredentialStore:
    def __init__(self) -> None:
        self.value: str | None = None

    def get(self) -> str | None:
        return self.value

    def set(self, value: str) -> None:
        self.value = value

    def clear(self) -> bool:
        was_configured = self.value is not None
        self.value = None
        return was_configured

    def status(self) -> object:
        from fbw_harness.credentials import CredentialStatus

        return CredentialStatus(self.value is not None, "fake-service", "fake-account")


def test_run_maps_structured_result_to_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    # Break caught: CLI stops returning the application result exit code/status summary.
    from fbw_harness.cli import main

    fake_app = FakeApplication()
    code = main(
        [
            "run",
            "--workspace",
            "project",
            "--task",
            "fix",
            "--base-url",
            "https://example.test/v1",
            "--model",
            "m",
        ],
        app=fake_app,
    )

    assert code == 0
    assert fake_app.requests == [RunRequest(Path("project"), "fix", "https://example.test/v1", "m")]
    assert "COMPLETED" in capsys.readouterr().out


def test_key_is_never_accepted_as_cli_argument() -> None:
    # Break caught: a key-bearing run argument would expose credentials in shell history/process lists.
    from fbw_harness.cli import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["run", "--api-key", "value"])


def test_credential_status_reports_only_metadata(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Break caught: credential status would print the stored secret instead of its configuration state.
    from fbw_harness.cli import main

    store = FakeCredentialStore()
    store.set("secret-value")

    assert main(["credential", "status"], credential_store=store) == 0
    output = capsys.readouterr().out
    assert "configured=True" in output
    assert "fake-service" in output
    assert "secret-value" not in output


def test_memory_clear_removes_only_workspace_memory(tmp_path: Path) -> None:
    # Break caught: memory clear fails to remove the configured project memory file.
    from fbw_harness.cli import main

    memory_file = tmp_path / ".fbw-memory.json"
    memory_file.write_text('{"version": 1}', encoding="utf-8")

    assert main(["memory", "clear", "--workspace", str(tmp_path)]) == 0
    assert not memory_file.exists()


def test_console_events_render_stable_round_and_test_category(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Break caught: state telemetry omits the stable test category needed for terminal progress.
    from fbw_harness.cli import ConsoleEventSink

    ConsoleEventSink().emit(RunEvent("a" * 32, "state", "verifying", {"round_count": 2}))

    assert capsys.readouterr().out == "[轮次 2] 测试: verifying\n"
