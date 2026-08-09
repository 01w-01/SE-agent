from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import BinaryIO

from .config import HarnessConfig
from .feedback import OutputRedactor
from .models import TestResult
from .workspace import Workspace

_TIMEOUT_EXIT_CODE = 124
_REAP_TIMEOUT_SECONDS = 1
_TASKKILL_TIMEOUT_SECONDS = 2
_START_ERRORS = (OSError, ValueError, RuntimeError)
_PROCESS_ERRORS = (OSError, ValueError, RuntimeError, subprocess.SubprocessError)
_DIAGNOSTIC_NEEDLES = (
    ("COLLECTION", (b"error collecting", b"error during collection")),
    ("SYNTAX", (b"syntaxerror",)),
    ("IMPORT", (b"importerror", b"modulenotfounderror")),
    ("ASSERTION", (b"assertionerror",)),
)
_DIAGNOSTIC_OVERLAP_BYTES = (
    max(len(needle) for _, needles in _DIAGNOSTIC_NEEDLES for needle in needles) - 1
)


class TestRunner:
    """Run the configured pytest selection without accepting a model-provided command."""

    def __init__(self, config: HarnessConfig, known_secrets: tuple[str, ...] = ()) -> None:
        self._config = config
        self._known_secrets = tuple(secret for secret in known_secrets if secret)

    def run(self, workspace: Path | Workspace) -> TestResult:
        started = time.perf_counter()
        try:
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
            process = subprocess.Popen(command, **process_options)
        except _START_ERRORS:
            return _start_failure(started)

        stdout_reader = _TailReader(
            process.stdout, self._config.output_tail_chars, self._known_secrets
        )
        stderr_reader = _TailReader(
            process.stderr, self._config.output_tail_chars, self._known_secrets
        )
        readers = (stdout_reader, stderr_reader)
        try:
            for reader in readers:
                reader.start()
            process.wait(timeout=self._config.pytest_timeout_seconds)
        except subprocess.TimeoutExpired:
            _stop_process(process)
            stdout, stderr = _finish_readers(readers)
            return TestResult(
                False,
                _TIMEOUT_EXIT_CODE,
                stdout,
                stderr,
                _elapsed(started),
                True,
            )
        except _PROCESS_ERRORS:
            _stop_process(process)
            _finish_readers(readers)
            return _start_failure(started)

        stdout, stderr = _finish_readers(readers)
        exit_code = process.returncode if isinstance(process.returncode, int) else 1
        return TestResult(
            exit_code == 0,
            exit_code,
            stdout,
            stderr,
            _elapsed(started),
        )


class _TailReader:
    """Continuously drain one pipe while retaining only a bounded byte tail."""

    def __init__(self, stream: BinaryIO | None, limit: int, known_secrets: tuple[str, ...]) -> None:
        self._stream = stream
        self._limit = max(1, limit)
        self._tail = bytearray()
        self._diagnostics: set[str] = set()
        self._scan_overlap = b""
        self._at_stream_start = True
        self._redactor = OutputRedactor(known_secrets)
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._started = False

    def start(self) -> None:
        self._thread.start()
        self._started = True

    def finish(self) -> str:
        if not self._started:
            self.close()
            return ""
        self._thread.join(timeout=_REAP_TIMEOUT_SECONDS)
        if self._thread.is_alive():
            self.close()
            self._thread.join(timeout=_REAP_TIMEOUT_SECONDS)
        markers = "".join(
            f"[FBW_DIAGNOSTIC:{name}]\n"
            for name, _ in _DIAGNOSTIC_NEEDLES
            if name in self._diagnostics
        )
        return markers + _decode(bytes(self._tail))

    def close(self) -> None:
        if self._stream is None:
            return
        try:
            self._stream.close()
        except (OSError, ValueError):
            pass

    def _drain(self) -> None:
        if self._stream is None:
            return
        chunk_size = min(8192, self._limit)
        try:
            while chunk := self._stream.read(chunk_size):
                self._scan_diagnostics(chunk)
                self._append_safe(self._redactor.feed(chunk))
        except (OSError, ValueError, RuntimeError, TypeError):
            pass
        finally:
            self._append_safe(self._redactor.finish())
            self.close()

    def _scan_diagnostics(self, chunk: bytes) -> None:
        window = (self._scan_overlap + chunk).lower()
        for name, needles in _DIAGNOSTIC_NEEDLES:
            if any(needle in window for needle in needles):
                self._diagnostics.add(name)
        if self._at_stream_start:
            if window.startswith(b"failed "):
                self._diagnostics.add("ASSERTION")
                self._at_stream_start = False
            elif not b"failed ".startswith(window):
                self._at_stream_start = False
        if b"\nfailed " in window:
            self._diagnostics.add("ASSERTION")
        self._scan_overlap = window[-_DIAGNOSTIC_OVERLAP_BYTES:]

    def _append_safe(self, chunk: bytes) -> None:
        if len(chunk) >= self._limit:
            self._tail[:] = chunk[-self._limit :]
            return
        self._tail.extend(chunk)
        overflow = len(self._tail) - self._limit
        if overflow > 0:
            del self._tail[:overflow]


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        completed = subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.pid)],
            check=False,
            capture_output=True,
            shell=False,
            timeout=_TASKKILL_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            raise OSError("process tree termination failed")
        return
    os.killpg(os.getpgid(process.pid), signal.SIGKILL)


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    tree_terminated = False
    try:
        _terminate_process_tree(process)
        tree_terminated = True
    except _PROCESS_ERRORS:
        _best_effort_kill(process)

    if _bounded_wait(process):
        return
    if tree_terminated:
        _best_effort_kill(process)
        _bounded_wait(process)


def _best_effort_kill(process: subprocess.Popen[bytes]) -> None:
    try:
        process.kill()
    except _PROCESS_ERRORS:
        pass


def _bounded_wait(process: subprocess.Popen[bytes]) -> bool:
    try:
        process.wait(timeout=_REAP_TIMEOUT_SECONDS)
    except _PROCESS_ERRORS:
        return False
    return True


def _finish_readers(readers: tuple[_TailReader, _TailReader]) -> tuple[str, str]:
    return readers[0].finish(), readers[1].finish()


def _decode(value: bytes | str) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _elapsed(started: float) -> float:
    return max(0.0, time.perf_counter() - started)


def _start_failure(started: float) -> TestResult:
    return TestResult(False, 1, "", "Unable to start pytest.", _elapsed(started))
