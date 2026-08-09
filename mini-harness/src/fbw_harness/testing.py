from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .config import HarnessConfig
from .models import TestResult
from .workspace import Workspace

_TIMEOUT_EXIT_CODE = 124


class TestRunner:
    """Run the configured pytest selection without accepting a model-provided command."""

    def __init__(self, config: HarnessConfig) -> None:
        self._config = config

    def run(self, workspace: Path | Workspace) -> TestResult:
        root = workspace.root if isinstance(workspace, Workspace) else Path(workspace).resolve()
        command = [sys.executable, "-m", "pytest", *self._config.pytest_args]
        process_options: dict[str, object] = {
            "cwd": root,
            "shell": False,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if os.name == "nt":
            process_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            process_options["start_new_session"] = True

        started = time.perf_counter()
        try:
            process = subprocess.Popen(command, **process_options)
        except OSError:
            return TestResult(False, 1, "", "Unable to start pytest.", _elapsed(started))

        try:
            stdout, stderr = process.communicate(timeout=self._config.pytest_timeout_seconds)
        except subprocess.TimeoutExpired as timeout:
            stdout = timeout.output or b""
            stderr = timeout.stderr or b""
            try:
                _terminate_process_tree(process)
                final_stdout, final_stderr = process.communicate(timeout=1)
                stdout = final_stdout or stdout
                stderr = final_stderr or stderr
            except (OSError, subprocess.SubprocessError):
                pass
            return TestResult(
                False,
                _TIMEOUT_EXIT_CODE,
                _decode(stdout),
                _decode(stderr),
                _elapsed(started),
                True,
            )

        exit_code = process.returncode
        return TestResult(
            exit_code == 0,
            exit_code,
            _decode(stdout),
            _decode(stderr),
            _elapsed(started),
        )


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        completed = subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.pid)],
            check=False,
            capture_output=True,
            shell=False,
        )
        if completed.returncode != 0:
            raise OSError("process tree termination failed")
        return
    os.killpg(os.getpgid(process.pid), signal.SIGKILL)


def _decode(value: bytes | str) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _elapsed(started: float) -> float:
    return max(0.0, time.perf_counter() - started)
