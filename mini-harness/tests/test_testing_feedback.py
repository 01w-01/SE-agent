from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

import fbw_harness.testing as testing_module
from fbw_harness.config import HarnessConfig
from fbw_harness.feedback import FeedbackEngine, OutputRedactor, fingerprint
from fbw_harness.models import (
    Feedback,
    FeedbackKind,
    Observation,
    PolicyDecision,
    PolicyLevel,
)
from fbw_harness.models import (
    TestResult as HarnessTestResult,
)
from fbw_harness.testing import TestRunner as HarnessTestRunner
from fbw_harness.workspace import Workspace


def _write_project(root: Path, source: str) -> Path:
    root.mkdir()
    (root / "test_example.py").write_text(source, encoding="utf-8")
    return root


def _run_project(root: Path, *, timeout: int = 10, args: tuple[str, ...] = ("-q",)):
    return HarnessTestRunner(
        HarnessConfig(pytest_timeout_seconds=timeout, pytest_args=args), known_secrets=()
    ).run(root)


def _result(
    *,
    exit_code: int = 1,
    stdout: str = "",
    stderr: str = "",
    timed_out: bool = False,
    failed_tests: tuple[str, ...] = (),
) -> HarnessTestResult:
    return HarnessTestResult(
        passed=not timed_out and exit_code == 0,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=0.01,
        timed_out=timed_out,
        failed_tests=failed_tests,
    )


def _stream_redact(payload: bytes, *, chunk_size: int = 1) -> str:
    redactor = OutputRedactor()
    safe = b"".join(
        redactor.feed(payload[offset : offset + chunk_size])
        for offset in range(0, len(payload), chunk_size)
    )
    return (safe + redactor.finish()).decode("utf-8", errors="replace")


def test_runner_runs_real_pytest_in_workspace_and_accepts_workspace_object(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path / "project",
        "from pathlib import Path\n\n"
        "def test_cwd_is_project():\n"
        "    assert Path.cwd() == Path(__file__).parent\n",
    )

    result = HarnessTestRunner(HarnessConfig(pytest_timeout_seconds=10), known_secrets=()).run(
        Workspace(project)
    )

    assert result.passed is True
    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.duration_seconds >= 0


def test_runner_requires_known_secrets_as_keyword_only() -> None:
    with pytest.raises(TypeError):
        HarnessTestRunner(HarnessConfig())
    with pytest.raises(TypeError):
        HarnessTestRunner(HarnessConfig(), ())  # type: ignore[misc]

    runner = HarnessTestRunner(HarnessConfig(), known_secrets=())

    assert isinstance(runner, HarnessTestRunner)


@pytest.mark.parametrize(
    "payload, hidden",
    [
        (b"authorization=Basic basic-private-value", "basic-private-value"),
        (b"AUTHORIZATION : Bearer bearer-private-value", "bearer-private-value"),
        (b'Authorization = "quoted-private-value"', "quoted-private-value"),
        (b"Authorization: eof-private-value", "eof-private-value"),
    ],
)
@pytest.mark.parametrize("chunk_size", [1, 3])
def test_output_redactor_handles_authorization_equals_colon_and_eof(
    payload: bytes, hidden: str, chunk_size: int
) -> None:
    safe = _stream_redact(payload, chunk_size=chunk_size)

    assert hidden not in safe
    assert "[REDACTED]" in safe


@pytest.mark.parametrize(
    "payload, hidden",
    [
        (b'{"api_key": "json-private-value", "note": "visible"}', "json-private-value"),
        (b"{'token':'dict-private-value','note':'visible'}", "dict-private-value"),
        (b'{"OPENAI_API_KEY":"upper-private-value"}', "upper-private-value"),
    ],
)
def test_output_redactor_handles_quoted_mapping_keys_across_single_byte_chunks(
    payload: bytes, hidden: str
) -> None:
    safe = _stream_redact(payload)

    assert hidden not in safe
    assert "[REDACTED]" in safe
    if b"note" in payload:
        assert "visible" in safe


def test_output_redactor_preserves_non_sensitive_quoted_prose_field() -> None:
    prose = b'He said "token count": visible text'

    assert _stream_redact(prose) == prose.decode("ascii")


def test_runner_and_feedback_redact_quoted_json_field_before_tail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sensitive_suffix = "J" * 6
    process = _CompletedProcess(
        stdout=b'{"api_key":"' + b"J" * 100_000,
        returncode=1,
    )
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)

    result = HarnessTestRunner(HarnessConfig(output_tail_chars=6), known_secrets=()).run(tmp_path)
    feedback = FeedbackEngine(6).from_test(result)

    assert sensitive_suffix not in result.stdout
    assert sensitive_suffix not in feedback.output_tail


def test_output_redactor_requires_left_boundary_for_sk_token_across_chunks() -> None:
    ordinary = b"task-abcdefghijk"
    secret = b"prefix " + b"s" + b"k-" + b"abcdefghijk"

    assert _stream_redact(ordinary) == ordinary.decode("ascii")
    assert "abcdefghijk" not in _stream_redact(secret)


@pytest.mark.parametrize(
    "payload, hidden",
    [
        (b'{"note":"}","api_key":"secret-one"}', "secret-one"),
        (b'{"note":"{,:[x]}","token":"secret-two"}', "secret-two"),
        (
            b'{"note":"escaped \\" } , : { text","password":"secret-three"}',
            "secret-three",
        ),
        (
            b'{"items":["} , : {", {"safe":"x"}], "api_key":"secret-four"}',
            "secret-four",
        ),
        (b'{"outer":{"items":[{"api_key":"secret-five"}]}}', "secret-five"),
    ],
)
@pytest.mark.parametrize("chunk_size", [1, 2, 3, 7, 10_000])
def test_output_redactor_ignores_structure_inside_mapping_strings(
    payload: bytes, hidden: str, chunk_size: int
) -> None:
    safe = _stream_redact(payload, chunk_size=chunk_size)

    assert safe == _stream_redact(payload, chunk_size=len(payload))
    assert hidden not in safe
    assert "[REDACTED]" in safe


@pytest.mark.parametrize(
    "payload, hidden",
    [
        (b'{"api_\\u006bey":"unicode-escaped-secret"}', "unicode-escaped-secret"),
        (b'{"to\\"ken":"quote-escaped-secret"}', "quote-escaped-secret"),
    ],
)
@pytest.mark.parametrize("chunk_size", [1, 2, 3, 7, 10_000])
def test_output_redactor_fail_closes_escaped_mapping_keys(
    payload: bytes, hidden: str, chunk_size: int
) -> None:
    safe = _stream_redact(payload, chunk_size=chunk_size)

    assert safe == _stream_redact(payload, chunk_size=len(payload))
    assert hidden not in safe
    assert "[REDACTED]" in safe


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 7, 10_000])
def test_output_redactor_preserves_unterminated_mapping_value_at_eof(
    chunk_size: int,
) -> None:
    payload = b'{"note":"unterminated } , : { and \\" quote'

    assert _stream_redact(payload, chunk_size=chunk_size) == payload.decode("ascii")


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 7, 10_000])
def test_output_redactor_preserves_mapping_external_quoted_prose(chunk_size: int) -> None:
    payload = b'prose "contains } , : { and \\" quote" unchanged'

    assert _stream_redact(payload, chunk_size=chunk_size) == payload.decode("ascii")


@pytest.mark.parametrize("chunk_size", [1, 7, 10_000])
def test_output_redactor_fail_closes_at_bounded_container_depth(chunk_size: int) -> None:
    hidden = "deep-private-value"
    payload = b"{" * 10_000 + b'"api_key":"' + hidden.encode() + b'"'
    redactor = OutputRedactor()
    safe = (
        b"".join(
            redactor.feed(payload[offset : offset + chunk_size])
            for offset in range(0, len(payload), chunk_size)
        )
        + redactor.finish()
    )

    assert hidden.encode() not in safe
    assert safe.count(b"[REDACTED]") == 1
    assert len(safe) <= 128
    assert len(redactor._mapping._containers) <= 64


@pytest.mark.parametrize(
    "payload, hidden",
    [
        (b'{"note":"api_key=EMBEDDEDSECRET"}', "EMBEDDEDSECRET"),
        (b'message="Authorization: Basic AUTHSECRET"', "AUTHSECRET"),
        (b'prose "token=QUOTESECRET" unchanged', "QUOTESECRET"),
        (b'{"API KEY":"SPACESECRET"}', "SPACESECRET"),
        (b'{"openai.api_key":"DOTSECRET"}', "DOTSECRET"),
    ],
)
@pytest.mark.parametrize("chunk_size", [1, 2, 3, 7, 10_000])
def test_output_redactor_scans_global_assignments_and_canonical_mapping_keys(
    payload: bytes, hidden: str, chunk_size: int
) -> None:
    safe = _stream_redact(payload, chunk_size=chunk_size)

    assert safe == _stream_redact(payload, chunk_size=len(payload))
    assert hidden not in safe
    assert "[REDACTED]" in safe


@pytest.mark.parametrize(
    "payload, hidden",
    [
        (b'prefix "token=' + b"RUNNERQUOTEDSECRET" * 8, "RUNNERQUOTEDSECRET"),
        (b'{"API KEY":"' + b"RUNNERSPACESECRET" * 8, "RUNNERSPACESECRET"),
        (b'{"openai.api_key":"' + b"RUNNERDOTSECRET" * 8, "RUNNERDOTSECRET"),
    ],
)
def test_runner_and_feedback_redact_adversarial_stream_before_mid_secret_tail(
    payload: bytes,
    hidden: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process = _CompletedProcess(stdout=payload, returncode=1)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)

    result = HarnessTestRunner(HarnessConfig(output_tail_chars=11), known_secrets=()).run(tmp_path)
    feedback = FeedbackEngine(11).from_test(result)

    assert hidden not in result.stdout
    assert hidden not in feedback.output_tail
    assert "[REDACTED]" in result.stdout
    assert "[REDACTED]" in feedback.output_tail
    assert len(result.stdout) <= 11
    assert len(feedback.output_tail) <= 11


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 7, 10_000])
def test_output_redactor_preserves_safe_quoted_diagnostics_and_task_sk_text(
    chunk_size: int,
) -> None:
    payload = (
        b'prose "status token count" https://example.test/a:b at 12:34 '
        b"AssertionError: expected task-sk-abcdefghijk"
    )

    assert _stream_redact(payload, chunk_size=chunk_size) == payload.decode("ascii")


@pytest.mark.parametrize("quoted", [False, True])
@pytest.mark.parametrize("chunk_size", [1, 7, 8192])
def test_output_redactor_suppresses_very_long_secret_with_bounded_state(
    quoted: bool, chunk_size: int
) -> None:
    value = b"Q" * 100_000
    payload = b"token=" + (b'"' if quoted else b"") + value
    redactor = OutputRedactor()
    emitted = bytearray()
    for offset in range(0, len(payload), chunk_size):
        emitted.extend(redactor.feed(payload[offset : offset + chunk_size]))
    emitted.extend(redactor.finish())

    assert b"Q" * 32 not in emitted
    assert emitted.count(b"[REDACTED]") == 1
    assert len(emitted) <= 32
    assert hasattr(redactor, "_mapping")
    assert hasattr(redactor, "_global")
    for layer in (redactor._mapping, redactor._global):
        for state in vars(layer).values():
            if isinstance(state, (bytes, bytearray, str, list, tuple)):
                assert len(state) <= 64


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 7, 10_000])
def test_output_redactor_handles_adjacent_secrets_escaped_quotes_and_eof(
    chunk_size: int,
) -> None:
    payload = (
        b'prose token="FIRSTSECRET\\"CONTINUEDSECRET" '
        b"password=SECONDSECRET authorization=THIRDSECRET"
    )
    safe = _stream_redact(payload, chunk_size=chunk_size)

    assert safe == _stream_redact(payload, chunk_size=len(payload))
    assert "FIRSTSECRET" not in safe
    assert "CONTINUEDSECRET" not in safe
    assert "SECONDSECRET" not in safe
    assert "THIRDSECRET" not in safe
    assert safe.count("[REDACTED]") == 3


@pytest.mark.parametrize("depth", [64, 65])
@pytest.mark.parametrize("chunk_size", [1, 7, 10_000])
def test_output_redactor_has_exact_64_container_depth_boundary(depth: int, chunk_size: int) -> None:
    hidden = b"DEPTHSECRET"
    payload = b"{" * depth + b'"api_key":"' + hidden + b'"' + b"}" * depth
    redactor = OutputRedactor()
    safe = (
        b"".join(
            redactor.feed(payload[offset : offset + chunk_size])
            for offset in range(0, len(payload), chunk_size)
        )
        + redactor.finish()
    )

    assert hidden not in safe
    assert safe.count(b"[REDACTED]") == 1
    assert hasattr(redactor, "_mapping")
    assert len(redactor._mapping._containers) <= 64
    if depth == 65:
        assert len(safe) <= 128
    else:
        assert safe.startswith(b"{" * 64)


@pytest.mark.parametrize(
    "payload, hidden",
    [
        (b'"api_key" : "FRAGMENTDOUBLESECRET"', "FRAGMENTDOUBLESECRET"),
        (b"'API KEY'='FRAGMENTSINGLESECRET'", "FRAGMENTSINGLESECRET"),
        (b"\"openai.api-key\" = 'FRAGMENTMIXEDSECRET'", "FRAGMENTMIXEDSECRET"),
    ],
)
@pytest.mark.parametrize("chunk_size", [1, 2, 3, 7, 10_000])
def test_output_redactor_remembers_standalone_quoted_field_fragments(
    payload: bytes, hidden: str, chunk_size: int
) -> None:
    safe = _stream_redact(payload, chunk_size=chunk_size)

    assert safe == _stream_redact(payload, chunk_size=len(payload))
    assert hidden not in safe
    assert "[REDACTED]" in safe


@pytest.mark.parametrize(
    "payload, hidden",
    [
        (b'"api_key": UNQUOTEDSECRET', "UNQUOTEDSECRET"),
        (b"'token'=plainsecret", "plainsecret"),
    ],
)
@pytest.mark.parametrize("chunk_size", [1, 2, 3, 7, 10_000])
def test_output_redactor_fail_closes_unquoted_value_after_quoted_sensitive_field(
    payload: bytes, hidden: str, chunk_size: int
) -> None:
    safe = _stream_redact(payload, chunk_size=chunk_size)

    assert safe == _stream_redact(payload, chunk_size=len(payload))
    assert hidden not in safe
    assert "[REDACTED]" in safe


def test_output_redactor_bounds_incomplete_quoted_field_candidate() -> None:
    redactor = OutputRedactor()

    redactor.feed(b'"' + b"A" * 100_000)

    assert len(redactor._global._fragment_buffer) <= 64


@pytest.mark.parametrize(
    "payload, hidden",
    [
        ('prefix "api_key" : "' + "EXTERNALDOUBLESECRET" * 8, "EXTERNALDOUBLESECRET"),
        ("prefix 'API KEY' = '" + "EXTERNALSINGLESECRET" * 8, "EXTERNALSINGLESECRET"),
    ],
)
def test_feedback_redacts_external_test_result_quoted_field_fragment_before_tail(
    payload: str, hidden: str
) -> None:
    feedback = FeedbackEngine(13).from_test(_result(stderr=payload))

    assert hidden not in feedback.output_tail
    assert "[REDACTED]" in feedback.output_tail


@pytest.mark.parametrize(
    "payload, hidden",
    [
        ('prefix "api_key": ' + "EXTERNALUNQUOTEDSECRET" * 8, "EXTERNALUNQUOTEDSECRET"),
        ("prefix 'token'=" + "externalplainsecret" * 8, "externalplainsecret"),
    ],
)
def test_feedback_redacts_external_unquoted_value_after_quoted_sensitive_field(
    payload: str, hidden: str
) -> None:
    feedback = FeedbackEngine(13).from_test(_result(stderr=payload))

    assert hidden not in feedback.output_tail
    assert "[REDACTED]" in feedback.output_tail


@pytest.mark.parametrize("entrypoint", ["runner", "engine", "redactor"])
@pytest.mark.parametrize(
    "known_secrets",
    [
        pytest.param(("",), id="empty"),
        pytest.param(("NONASCII-\u5bc6\u5bc6",), id="non-ascii"),
        pytest.param((object(),), id="non-string"),
    ],
)
def test_known_secret_entrypoints_reject_invalid_values_without_leaking_exception_graph(
    entrypoint: str, known_secrets: tuple[object, ...]
) -> None:
    with pytest.raises(ValueError) as caught:
        if entrypoint == "runner":
            HarnessTestRunner(HarnessConfig(), known_secrets=known_secrets)  # type: ignore[arg-type]
        elif entrypoint == "engine":
            FeedbackEngine(100, known_secrets=known_secrets)  # type: ignore[arg-type]
        else:
            OutputRedactor(known_secrets)  # type: ignore[arg-type]

    exception_graph = " ".join(
        (
            str(caught.value),
            repr(caught.value),
            repr(caught.value.__cause__),
            repr(caught.value.__context__),
        )
    )
    assert str(caught.value) == "known_secrets must contain non-empty ASCII strings"
    for value in known_secrets:
        if isinstance(value, str) and value:
            assert value not in exception_graph


def test_known_secret_ascii_matching_is_case_insensitive_across_runner_and_feedback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configured = "MiXeD-Ascii-Private"
    emitted = configured.swapcase()
    process = _CompletedProcess(stdout=f"prefix {emitted}".encode(), returncode=1)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)

    result = HarnessTestRunner(
        HarnessConfig(output_tail_chars=100), known_secrets=(configured,)
    ).run(tmp_path)
    feedback = FeedbackEngine(100, known_secrets=(configured,)).from_test(result)

    assert emitted not in result.stdout
    assert emitted not in feedback.output_tail
    assert "[REDACTED]" in result.stdout


def test_runner_reports_real_assertion_failure(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path / "project", "def test_clamp_boundary():\n    assert 11 == 10\n"
    )

    result = _run_project(project)

    assert result.passed is False
    assert result.exit_code != 0
    assert "test_clamp_boundary" in result.stdout + result.stderr


@pytest.mark.parametrize(
    "source, marker",
    [
        ("def test_broken(:\n    pass\n", "SyntaxError"),
        ("import package_that_does_not_exist_fbw\n", "ModuleNotFoundError"),
        ("raise RuntimeError('collect boom')\n", "RuntimeError"),
    ],
)
def test_runner_returns_real_collection_diagnostics(
    tmp_path: Path, source: str, marker: str
) -> None:
    project = _write_project(tmp_path / "project", source)

    result = _run_project(project)

    assert result.passed is False
    assert result.exit_code != 0
    assert marker in result.stdout + result.stderr


def test_runner_times_out_real_pytest(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path / "project", "import time\n\ndef test_slow():\n    time.sleep(30)\n"
    )

    result = _run_project(project, timeout=1)

    assert result.passed is False
    assert result.timed_out is True
    assert result.exit_code == 124


def test_runner_does_not_interpret_pytest_argument_as_shell_syntax(tmp_path: Path) -> None:
    project = _write_project(tmp_path / "project", "def test_ok():\n    assert True\n")
    marker = project / "should-not-exist"
    injected_argument = f"missing.py;{sys.executable} -c marker.write_text('bad')"

    result = _run_project(project, args=(injected_argument,))

    assert result.passed is False
    assert marker.exists() is False


@pytest.mark.parametrize("error_type", [OSError, ValueError, RuntimeError])
def test_runner_maps_root_resolution_errors_without_leaking_details(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error_type: type[Exception]
) -> None:
    secret = "private-root-resolution-detail"

    def fail_resolve(self: Path, strict: bool = False) -> Path:
        raise error_type(secret)

    monkeypatch.setattr(Path, "resolve", fail_resolve)

    result = HarnessTestRunner(HarnessConfig(), known_secrets=()).run(tmp_path)

    assert result.passed is False
    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == "Unable to start pytest."
    assert secret not in result.stderr


@pytest.mark.parametrize("error_type", [OSError, ValueError, RuntimeError])
def test_runner_maps_process_start_errors_without_leaking_details(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error_type: type[Exception]
) -> None:
    secret = "private-process-start-detail"
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(error_type(secret)),
    )

    result = HarnessTestRunner(HarnessConfig(), known_secrets=()).run(tmp_path)

    assert result.passed is False
    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == "Unable to start pytest."
    assert secret not in result.stderr


def test_runner_maps_command_construction_runtime_error_without_leaking_details(
    tmp_path: Path,
) -> None:
    secret = "private-command-construction-detail"

    class ExplodingArgs(tuple[str, ...]):
        def __iter__(self):
            raise RuntimeError(secret)

    result = HarnessTestRunner(HarnessConfig(pytest_args=ExplodingArgs()), known_secrets=()).run(
        tmp_path
    )

    assert result.passed is False
    assert result.exit_code == 1
    assert result.stderr == "Unable to start pytest."
    assert secret not in result.stderr


def test_runner_maps_nul_pytest_argument_to_stable_start_failure(tmp_path: Path) -> None:
    secret = "private-nul-argument"

    result = HarnessTestRunner(HarnessConfig(pytest_args=("\x00" + secret,)), known_secrets=()).run(
        tmp_path
    )

    assert result.passed is False
    assert result.exit_code == 1
    assert result.stderr == "Unable to start pytest."
    assert secret not in result.stderr


def test_runner_bounds_stdout_and_stderr_while_draining_both_pipes(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path / "project",
        "import os\n\n"
        "def test_high_output():\n"
        "    os.write(1, b'O' * 1_000_000)\n"
        "    os.write(2, b'E' * 1_000_000)\n",
    )
    config = HarnessConfig(
        pytest_timeout_seconds=10,
        output_tail_chars=256,
        pytest_args=("-q", "-s"),
    )

    result = HarnessTestRunner(config, known_secrets=()).run(project)

    assert result.passed is True
    assert len(result.stdout) <= 256
    assert len(result.stderr) <= 256
    assert "passed" in result.stdout
    assert "E" in result.stderr


class _CompletedProcess:
    def __init__(
        self,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int = 0,
        wait_outcomes: list[int | BaseException] | None = None,
    ):
        self.stdout = BytesIO(stdout)
        self.stderr = BytesIO(stderr)
        self.returncode = returncode
        self.pid = 4321
        self.wait_outcomes = wait_outcomes or [returncode]
        self.wait_timeouts: list[float | None] = []
        self.kill_calls = 0

    def wait(self, timeout: float | None = None) -> int:
        self.wait_timeouts.append(timeout)
        outcome = self.wait_outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        self.returncode = outcome
        return outcome

    def kill(self) -> None:
        self.kill_calls += 1


def test_runner_builds_fixed_command_without_shell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_popen(command: list[str], **kwargs: object) -> _CompletedProcess:
        captured["command"] = command
        captured.update(kwargs)
        return _CompletedProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    config = HarnessConfig(pytest_args=("-q", "tests/unit"))

    result = HarnessTestRunner(config, known_secrets=()).run(tmp_path)

    assert result.passed is True
    assert captured["command"] == [sys.executable, "-m", "pytest", "-q", "tests/unit"]
    assert captured["cwd"] == tmp_path.resolve()
    assert captured["shell"] is False
    assert captured["stdout"] is subprocess.PIPE
    assert captured["stderr"] is subprocess.PIPE
    if os.name == "nt":
        assert captured["creationflags"] == subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        assert captured["start_new_session"] is True


def test_runner_decodes_non_utf8_with_replacement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *args, **kwargs: _CompletedProcess(b"out\xff", b"err\xfe", returncode=1),
    )

    result = HarnessTestRunner(HarnessConfig(), known_secrets=()).run(tmp_path)

    assert result.passed is False
    assert result.stdout == "out\ufffd"
    assert result.stderr == "err\ufffd"


def test_runner_returns_stable_failure_when_second_reader_cannot_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = "private-reader-start-detail"
    process = _CompletedProcess(wait_outcomes=[0])
    stopped: list[int] = []
    start_calls = 0
    original_start = testing_module.threading.Thread.start

    def fail_second_start(thread: testing_module.threading.Thread) -> None:
        nonlocal start_calls
        start_calls += 1
        if start_calls == 2:
            raise RuntimeError(secret)
        original_start(thread)

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(testing_module.threading.Thread, "start", fail_second_start)
    monkeypatch.setattr(
        testing_module,
        "_terminate_process_tree",
        lambda current: stopped.append(current.pid),
    )

    result = HarnessTestRunner(HarnessConfig(), known_secrets=()).run(tmp_path)

    assert result == HarnessTestResult(
        False, 1, "", "Unable to start pytest.", result.duration_seconds
    )
    assert stopped == [4321]
    assert process.wait_timeouts == [1]
    assert secret not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "early_diagnostic, expected_kind",
    [
        (b"ERROR collecting test_early.py", FeedbackKind.COLLECTION_FAILURE),
        (b"SyntaxError: early invalid syntax", FeedbackKind.SYNTAX_ERROR),
        (b"ModuleNotFoundError: early missing module", FeedbackKind.IMPORT_ERROR),
        (b"AssertionError: early mismatch", FeedbackKind.ASSERTION_FAILURE),
        (b"\nFAILED tests/test_early.py::test_x - assert 1 == 2", FeedbackKind.ASSERTION_FAILURE),
    ],
)
def test_runner_preserves_fixed_early_diagnostic_fact_with_bounded_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    early_diagnostic: bytes,
    expected_kind: FeedbackKind,
) -> None:
    noise = b"N" * 100_000
    process = _CompletedProcess(
        stdout=b"\xff" + early_diagnostic + b"\xfe" + noise,
        returncode=1,
    )
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)

    result = HarnessTestRunner(HarnessConfig(output_tail_chars=7), known_secrets=()).run(tmp_path)
    feedback = FeedbackEngine(7).from_test(result)

    assert feedback.kind is expected_kind
    assert len(result.stdout) <= 96
    assert result.stdout.endswith("N" * 7)
    assert early_diagnostic.decode("ascii") not in result.stdout


def test_runner_detects_stream_start_failed_across_three_byte_chunks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    process = _CompletedProcess(
        stdout=b"FAILED tests/test_early.py::test_x - assert 1 == 2" + b"N" * 10_000,
        returncode=1,
    )
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)

    result = HarnessTestRunner(HarnessConfig(output_tail_chars=3), known_secrets=()).run(tmp_path)

    assert FeedbackEngine(3).from_test(result).kind is FeedbackKind.ASSERTION_FAILURE


@pytest.mark.parametrize(
    "prefix, secret_byte",
    [
        (b"Authorization: Bearer ", b"A"),
        (b"Bearer ", b"B"),
        (b'OPENAI_API_KEY="', b"C"),
        (b"plain " + b"s" + b"k-", b"D"),
    ],
)
def test_runner_redacts_generic_secret_stream_before_bounded_tail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    prefix: bytes,
    secret_byte: bytes,
) -> None:
    sensitive_suffix = secret_byte * 5
    process = _CompletedProcess(
        stdout=prefix + secret_byte * 100_000,
        returncode=1,
    )
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)

    result = HarnessTestRunner(HarnessConfig(output_tail_chars=5), known_secrets=()).run(tmp_path)
    feedback = FeedbackEngine(5).from_test(result)

    assert len(result.stdout) <= 5
    assert sensitive_suffix.decode("ascii") not in result.stdout
    assert sensitive_suffix.decode("ascii") not in feedback.output_tail


def test_runner_redacts_known_secret_across_chunks_before_bounded_tail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    known_secret = "known-" + "K" * 80
    sensitive_suffix = "K" * 4
    process = _CompletedProcess(
        stdout=b"prefix " + known_secret.encode("utf-8"),
        returncode=1,
    )
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)

    result = HarnessTestRunner(
        HarnessConfig(output_tail_chars=4), known_secrets=(known_secret,)
    ).run(tmp_path)
    feedback = FeedbackEngine(4, known_secrets=(known_secret,)).from_test(result)

    assert len(result.stdout) <= 4
    assert known_secret not in result.stdout
    assert sensitive_suffix not in result.stdout
    assert sensitive_suffix not in feedback.output_tail


def test_feedback_strips_internal_marker_before_multibyte_tail() -> None:
    result = _result(
        stderr="[FBW_DIAGNOSTIC:SYNTAX]\n前🙂后",
        exit_code=1,
    )

    feedback = FeedbackEngine(100).from_test(result)

    assert feedback.kind is FeedbackKind.SYNTAX_ERROR
    assert feedback.output_tail == "前🙂后"
    assert "FBW_DIAGNOSTIC" not in feedback.output_tail


@pytest.mark.skipif(os.name != "nt", reason="Windows taskkill contract")
def test_windows_timeout_kills_entire_process_tree_with_fixed_arguments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    process = _CompletedProcess(
        stdout=b"after",
        wait_outcomes=[subprocess.TimeoutExpired("pytest", 1), 124],
    )
    taskkill_calls: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **kwargs: (
            taskkill_calls.append((command, kwargs)) or SimpleNamespace(returncode=0)
        ),
    )

    result = HarnessTestRunner(HarnessConfig(pytest_timeout_seconds=1), known_secrets=()).run(
        tmp_path
    )

    assert result.timed_out is True
    assert taskkill_calls == [
        (
            ["taskkill", "/T", "/F", "/PID", "4321"],
            {"check": False, "capture_output": True, "shell": False, "timeout": 2},
        )
    ]
    assert process.wait_timeouts == [1, 1]


@pytest.mark.skipif(os.name != "nt", reason="Windows taskkill contract")
def test_windows_taskkill_nonzero_uses_only_bounded_reap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    process = _CompletedProcess(wait_outcomes=[subprocess.TimeoutExpired("pytest", 1), 124])
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1),
    )

    result = HarnessTestRunner(HarnessConfig(pytest_timeout_seconds=1), known_secrets=()).run(
        tmp_path
    )

    assert result.timed_out is True
    assert result.exit_code == 124
    assert process.wait_timeouts == [1, 1]
    assert process.kill_calls == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows taskkill contract")
def test_windows_taskkill_timeout_returns_stable_result_with_bounded_reap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = "private-taskkill-timeout-detail"
    process = _CompletedProcess(wait_outcomes=[subprocess.TimeoutExpired("pytest", 1), 124])
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired(secret, 2)),
    )

    result = HarnessTestRunner(HarnessConfig(pytest_timeout_seconds=1), known_secrets=()).run(
        tmp_path
    )

    assert result.timed_out is True
    assert result.exit_code == 124
    assert process.wait_timeouts == [1, 1]
    assert process.kill_calls == 1
    assert secret not in result.stdout + result.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group contract")
def test_posix_timeout_kills_process_group(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    process = _CompletedProcess(wait_outcomes=[subprocess.TimeoutExpired("pytest", 1), 124])
    killed: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(os, "getpgid", lambda pid: 9876)
    monkeypatch.setattr(os, "killpg", lambda group, sig: killed.append((group, sig)))

    result = HarnessTestRunner(HarnessConfig(pytest_timeout_seconds=1), known_secrets=()).run(
        tmp_path
    )

    assert result.timed_out is True
    assert killed == [(9876, signal.SIGKILL)]
    assert process.wait_timeouts == [1, 1]


def test_timeout_returns_stable_result_when_tree_termination_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = "sk-" + "termination-secret"

    process = _CompletedProcess(
        wait_outcomes=[
            subprocess.TimeoutExpired("pytest", 1),
            subprocess.TimeoutExpired("pytest", 1),
        ]
    )
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    if os.name == "nt":
        monkeypatch.setattr(
            subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(OSError(secret))
        )
    else:
        monkeypatch.setattr(os, "getpgid", lambda pid: (_ for _ in ()).throw(OSError(secret)))

    result = HarnessTestRunner(HarnessConfig(pytest_timeout_seconds=1), known_secrets=()).run(
        tmp_path
    )

    assert result == HarnessTestResult(False, 124, "", "", result.duration_seconds, True)
    assert secret not in result.stdout + result.stderr
    assert process.wait_timeouts == [1, 1]
    assert process.kill_calls == 1


@pytest.mark.parametrize(
    "result, expected",
    [
        (_result(exit_code=0), FeedbackKind.PASSED),
        (_result(timed_out=True), FeedbackKind.TIMEOUT),
        (_result(stdout="ERROR collecting test_bad.py"), FeedbackKind.COLLECTION_FAILURE),
        (_result(stderr="SyntaxError: invalid syntax"), FeedbackKind.SYNTAX_ERROR),
        (_result(stdout="ImportError: cannot import name 'x'"), FeedbackKind.IMPORT_ERROR),
        (_result(stderr="AssertionError: mismatch"), FeedbackKind.ASSERTION_FAILURE),
        (_result(exit_code=7), FeedbackKind.UNKNOWN_TEST_FAILURE),
    ],
)
def test_feedback_classifies_test_results_by_priority(
    result: HarnessTestResult, expected: FeedbackKind
) -> None:
    feedback = FeedbackEngine(200).from_test(result)

    assert feedback.kind is expected
    assert feedback.passed is (expected is FeedbackKind.PASSED)


def test_feedback_timeout_has_priority_over_other_markers() -> None:
    result = _result(
        stdout="ERROR collecting test_x.py SyntaxError ImportError AssertionError",
        timed_out=True,
    )

    assert FeedbackEngine(100).from_test(result).kind is FeedbackKind.TIMEOUT


def test_feedback_extracts_conservative_sorted_unique_pytest_node_ids() -> None:
    result = _result(
        stdout=(
            "FAILED tests/test_b.py::test_z - AssertionError\n"
            "FAILED tests/test_a.py::TestClamp::test_low - assert 0\n"
            "FAILED tests/test_b.py::test_z - AssertionError\n"
            "not-a-node:: ../../private.txt\n"
        ),
        failed_tests=("tests/test_c.py::test_x", "tests/test_a.py::TestClamp::test_low"),
    )

    feedback = FeedbackEngine(500).from_test(result)

    assert feedback.failed_tests == (
        "tests/test_a.py::TestClamp::test_low",
        "tests/test_b.py::test_z",
        "tests/test_c.py::test_x",
    )


def test_feedback_does_not_invent_failure_details_for_empty_unknown_output() -> None:
    feedback = FeedbackEngine(100).from_test(_result(exit_code=9))

    assert feedback.kind is FeedbackKind.UNKNOWN_TEST_FAILURE
    assert feedback.failed_tests == ()
    assert "expected" not in feedback.summary.casefold()
    assert "actual" not in feedback.summary.casefold()


def test_feedback_rejects_untrusted_failed_test_names() -> None:
    secret = "sk-" + "malicious-failed-test-name"
    absolute = str(Path.cwd().resolve() / "test_private.py::test_secret")
    result = _result(
        stderr="AssertionError",
        failed_tests=(absolute, secret, "tests/test_safe.py::test_public"),
    )

    feedback = FeedbackEngine(100, known_secrets=(secret,)).from_test(result)

    assert feedback.failed_tests == ("tests/test_safe.py::test_public",)


@pytest.mark.parametrize(
    "unsafe_node_id",
    [
        "C:/tests/test_private.py::test_secret",
        "C:\\tests\\test_private.py::test_secret",
        "/tests/test_private.py::test_secret",
        "tests//test_private.py::test_secret",
        "tests\\\\test_private.py::test_secret",
        "./tests/test_private.py::test_secret",
        ".\\tests\\test_private.py::test_secret",
        "../tests/test_private.py::test_secret",
        "..\\tests\\test_private.py::test_secret",
        "tests/../test_private.py::test_secret",
        "tests\\..\\test_private.py::test_secret",
    ],
)
def test_feedback_rejects_rooted_or_noncanonical_node_ids(unsafe_node_id: str) -> None:
    result = _result(
        stderr=f"FAILED {unsafe_node_id} - AssertionError",
        failed_tests=(unsafe_node_id,),
    )

    feedback = FeedbackEngine(200).from_test(result)

    assert feedback.failed_tests == ()


@pytest.mark.parametrize(
    "unsafe_node_id, known_secrets",
    [
        ("tests/test_" + "sk-" + "abcdefghijklmnop.py::test_x", ()),
        ("tests/test_private_marker.py::test_x", ("private_marker",)),
    ],
)
def test_feedback_drops_node_id_if_redaction_would_change_it(
    unsafe_node_id: str, known_secrets: tuple[str, ...]
) -> None:
    result = _result(
        stderr=f"FAILED {unsafe_node_id} - AssertionError",
        failed_tests=(unsafe_node_id,),
    )

    feedback = FeedbackEngine(200, known_secrets=known_secrets).from_test(result)

    assert feedback.failed_tests == ()


@pytest.mark.parametrize(
    "secret_line",
    [
        "Authorization: Basic very-private-value",
        "authorization=Bearer bearer-private-value",
        "api_key = 'api-private-value'",
        'KEY="key-private-value"',
        "secret: secret-private-value",
        "password=password-private-value",
        "token = token-private-value",
        "plain " + "sk-" + "abcdefghijklmnopqrstuvwxyz0123456789",
    ],
)
def test_feedback_redacts_common_secret_forms_before_truncating(secret_line: str) -> None:
    result = _result(stderr=f"safe-prefix {secret_line} safe-suffix")

    feedback = FeedbackEngine(18).from_test(result)

    assert "private-value" not in feedback.output_tail
    assert "abcdefghijklmnopqrstuvwxyz" not in feedback.output_tail
    assert len(feedback.output_tail) <= 18


@pytest.mark.parametrize(
    "secret_line",
    [
        'OPENAI_API_KEY = "openai-private-value"',
        "anthropic_api_key='anthropic-private-value'",
        "DATABASE_PASSWORD = database-private-value",
        "service_ToKeN: 'token-private-value'",
        'nested_client_secret="client-private-value"',
    ],
)
def test_feedback_redacts_sensitive_suffix_variable_assignments_before_truncating(
    secret_line: str,
) -> None:
    feedback = FeedbackEngine(20).from_test(_result(stderr=f"prefix {secret_line} suffix"))

    assert "private-value" not in feedback.output_tail
    assert len(feedback.output_tail) <= 20


def test_feedback_redacts_known_secrets_and_absolute_workspace_paths() -> None:
    secret = "known-value-12345"
    absolute = str(Path.cwd().resolve() / "tests" / "test_secret.py")
    result = _result(stderr=f"failure at {absolute}: {secret}")

    feedback = FeedbackEngine(500, known_secrets=(secret,)).from_test(result)

    combined = feedback.summary + feedback.output_tail
    assert secret not in combined
    assert str(Path.cwd().resolve()) not in combined
    assert "test_secret.py" not in combined


def test_feedback_from_policy_and_tool_never_copies_untrusted_details() -> None:
    secret = "sk-" + "untrusted-policy-tool-secret"
    path = str(Path.cwd().resolve() / "private.py")
    engine = FeedbackEngine(500, known_secrets=(secret,))
    policy = PolicyDecision(PolicyLevel.DENY, secret, f"bad {path}", (secret, path))
    observation = Observation(secret, False, f"bad {path}", 17, f"tail {secret} {path}")

    policy_feedback = engine.from_policy(policy)
    tool_feedback = engine.from_tool(observation)

    assert policy_feedback.kind is FeedbackKind.POLICY_DENIED
    assert tool_feedback.kind is FeedbackKind.TOOL_ERROR
    assert policy_feedback.passed is None
    assert tool_feedback.passed is None
    assert tool_feedback.exit_code == 17
    for value in (policy_feedback, tool_feedback):
        serialized = value.summary + value.output_tail + value.fingerprint
        assert secret not in serialized
        assert path not in serialized


@pytest.mark.parametrize("level", [PolicyLevel.ALLOW, PolicyLevel.CONFIRM])
def test_feedback_from_policy_rejects_non_deny_without_untrusted_details(
    level: PolicyLevel,
) -> None:
    secret = "private-policy-detail"
    decision = PolicyDecision(level, secret, secret, (secret,))

    with pytest.raises(ValueError) as caught:
        FeedbackEngine(100, known_secrets=(secret,)).from_policy(decision)

    assert str(caught.value) == "policy feedback requires a denied decision"
    assert secret not in str(caught.value)


def test_feedback_from_tool_rejects_success_without_untrusted_details() -> None:
    secret = "private-tool-detail"
    observation = Observation(secret, True, secret, 0, secret)

    with pytest.raises(ValueError) as caught:
        FeedbackEngine(100, known_secrets=(secret,)).from_tool(observation)

    assert str(caught.value) == "tool feedback requires a failed observation"
    assert secret not in str(caught.value)


def test_feedback_fingerprint_is_canonical_and_excludes_output_tail() -> None:
    first = Feedback(
        FeedbackKind.ASSERTION_FAILURE,
        False,
        1,
        " Assertion   failed\r\n in clamp ",
        ("tests/test_b.py::test_b", "tests/test_a.py::test_a", "tests/test_b.py::test_b"),
        "first raw tail",
    )
    equivalent = Feedback(
        FeedbackKind.ASSERTION_FAILURE,
        False,
        1,
        "Assertion failed in clamp",
        ("tests/test_a.py::test_a", "tests/test_b.py::test_b"),
        "completely different tail",
    )

    first_hash = fingerprint(first)

    assert first_hash == fingerprint(equivalent)
    assert re.fullmatch(r"[0-9a-f]{64}", first_hash)


@pytest.mark.parametrize(
    "changed",
    [
        Feedback(FeedbackKind.IMPORT_ERROR, False, 1, "same", ("test_x.py::test_x",)),
        Feedback(FeedbackKind.ASSERTION_FAILURE, False, 2, "same", ("test_x.py::test_x",)),
        Feedback(FeedbackKind.ASSERTION_FAILURE, False, 1, "different", ("test_x.py::test_x",)),
    ],
)
def test_feedback_fingerprint_changes_for_meaningful_fields(changed: Feedback) -> None:
    baseline = Feedback(
        FeedbackKind.ASSERTION_FAILURE,
        False,
        1,
        "same",
        ("test_x.py::test_x",),
    )

    assert fingerprint(changed) != fingerprint(baseline)
