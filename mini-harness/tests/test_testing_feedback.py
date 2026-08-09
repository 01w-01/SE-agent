from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from fbw_harness.config import HarnessConfig
from fbw_harness.feedback import FeedbackEngine, fingerprint
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
    return HarnessTestRunner(HarnessConfig(pytest_timeout_seconds=timeout, pytest_args=args)).run(
        root
    )


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


def test_runner_runs_real_pytest_in_workspace_and_accepts_workspace_object(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path / "project",
        "from pathlib import Path\n\n"
        "def test_cwd_is_project():\n"
        "    assert Path.cwd() == Path(__file__).parent\n",
    )

    result = HarnessTestRunner(HarnessConfig(pytest_timeout_seconds=10)).run(Workspace(project))

    assert result.passed is True
    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.duration_seconds >= 0


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


class _CompletedProcess:
    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.pid = 4321

    def communicate(self, timeout: int | None = None) -> tuple[bytes, bytes]:
        return self.stdout, self.stderr


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

    result = HarnessTestRunner(config).run(tmp_path)

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

    result = HarnessTestRunner(HarnessConfig()).run(tmp_path)

    assert result.passed is False
    assert result.stdout == "out\ufffd"
    assert result.stderr == "err\ufffd"


@pytest.mark.skipif(os.name != "nt", reason="Windows taskkill contract")
def test_windows_timeout_kills_entire_process_tree_with_fixed_arguments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class TimedOutProcess(_CompletedProcess):
        calls = 0

        def communicate(self, timeout: int | None = None) -> tuple[bytes, bytes]:
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("pytest", timeout or 1, output=b"partial")
            return b"after", b""

    process = TimedOutProcess()
    taskkill_calls: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **kwargs: (
            taskkill_calls.append((command, kwargs)) or SimpleNamespace(returncode=0)
        ),
    )

    result = HarnessTestRunner(HarnessConfig(pytest_timeout_seconds=1)).run(tmp_path)

    assert result.timed_out is True
    assert taskkill_calls == [
        (
            ["taskkill", "/T", "/F", "/PID", "4321"],
            {"check": False, "capture_output": True, "shell": False},
        )
    ]


@pytest.mark.skipif(os.name != "nt", reason="Windows taskkill contract")
def test_windows_taskkill_nonzero_returns_without_waiting_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class TimedOutProcess(_CompletedProcess):
        calls = 0

        def communicate(self, timeout: int | None = None) -> tuple[bytes, bytes]:
            self.calls += 1
            if self.calls > 1:
                raise AssertionError("runner waited after taskkill reported failure")
            raise subprocess.TimeoutExpired("pytest", timeout or 1)

    process = TimedOutProcess()
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1),
    )

    result = HarnessTestRunner(HarnessConfig(pytest_timeout_seconds=1)).run(tmp_path)

    assert result.timed_out is True
    assert result.exit_code == 124
    assert process.calls == 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group contract")
def test_posix_timeout_kills_process_group(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class TimedOutProcess(_CompletedProcess):
        calls = 0

        def communicate(self, timeout: int | None = None) -> tuple[bytes, bytes]:
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("pytest", timeout or 1)
            return b"", b""

    process = TimedOutProcess()
    killed: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(os, "getpgid", lambda pid: 9876)
    monkeypatch.setattr(os, "killpg", lambda group, sig: killed.append((group, sig)))

    result = HarnessTestRunner(HarnessConfig(pytest_timeout_seconds=1)).run(tmp_path)

    assert result.timed_out is True
    assert killed == [(9876, signal.SIGKILL)]


def test_timeout_returns_stable_result_when_tree_termination_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = "sk-termination-secret"

    class TimedOutProcess(_CompletedProcess):
        def communicate(self, timeout: int | None = None) -> tuple[bytes, bytes]:
            raise subprocess.TimeoutExpired("pytest", timeout or 1)

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: TimedOutProcess())
    if os.name == "nt":
        monkeypatch.setattr(
            subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(OSError(secret))
        )
    else:
        monkeypatch.setattr(os, "getpgid", lambda pid: (_ for _ in ()).throw(OSError(secret)))

    result = HarnessTestRunner(HarnessConfig(pytest_timeout_seconds=1)).run(tmp_path)

    assert result == HarnessTestResult(False, 124, "", "", result.duration_seconds, True)
    assert secret not in result.stdout + result.stderr


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
    secret = "sk-malicious-failed-test-name"
    absolute = str(Path.cwd().resolve() / "test_private.py::test_secret")
    result = _result(
        stderr="AssertionError",
        failed_tests=(absolute, secret, "tests/test_safe.py::test_public"),
    )

    feedback = FeedbackEngine(100, known_secrets=(secret,)).from_test(result)

    assert feedback.failed_tests == ("tests/test_safe.py::test_public",)


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
        "plain [REDACTED-HISTORICAL-TOKEN]",
    ],
)
def test_feedback_redacts_common_secret_forms_before_truncating(secret_line: str) -> None:
    result = _result(stderr=f"safe-prefix {secret_line} safe-suffix")

    feedback = FeedbackEngine(18).from_test(result)

    assert "private-value" not in feedback.output_tail
    assert "abcdefghijklmnopqrstuvwxyz" not in feedback.output_tail
    assert len(feedback.output_tail) <= 18


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
    secret = "sk-untrusted-policy-tool-secret"
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
