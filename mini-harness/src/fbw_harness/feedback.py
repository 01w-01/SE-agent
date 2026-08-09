from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace

from .models import Feedback, FeedbackKind, Observation, PolicyDecision, PolicyLevel, TestResult

_NODE_ID = r"(?:[A-Za-z0-9_.-]+[\\/])*[A-Za-z0-9_.-]+\.py(?:::[A-Za-z0-9_\[\].-]+)+"
_NODE_ID_PATTERN = re.compile(rf"(?m)^FAILED\s+({_NODE_ID})(?:\s|$)")
_NODE_ID_FULL_PATTERN = re.compile(rf"{_NODE_ID}\Z")
_WINDOWS_PATH_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9_])[A-Z]:[\\/](?:[^\\/\r\n:]+[\\/])*[^\\/\r\n:]*"
)
_POSIX_PATH_PATTERN = re.compile(r"(?<![A-Za-z0-9_.-])/(?:[^/\s:]+/)+[^/\s:]*")
_INTERNAL_MARKER_PATTERN = re.compile(
    r"(?i)\[FBW_DIAGNOSTIC:(?:COLLECTION|SYNTAX|IMPORT|ASSERTION)\]\r?\n?"
)
_REDACTED = b"[REDACTED]"
_SENSITIVE_SUFFIXES = (b"key", b"secret", b"password", b"token")
_VALUE_DELIMITERS = frozenset(b" \t\r\n,;")
_TOKEN_BYTES = frozenset(b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")

_SUMMARY_BY_KIND = {
    FeedbackKind.PASSED: "Pytest passed.",
    FeedbackKind.ASSERTION_FAILURE: "Pytest reported an assertion failure.",
    FeedbackKind.COLLECTION_FAILURE: "Pytest failed while collecting tests.",
    FeedbackKind.SYNTAX_ERROR: "Pytest reported a syntax error.",
    FeedbackKind.IMPORT_ERROR: "Pytest reported an import error.",
    FeedbackKind.TIMEOUT: "Pytest exceeded the configured timeout.",
    FeedbackKind.UNKNOWN_TEST_FAILURE: "Pytest failed for an unknown reason.",
}


class OutputRedactor:
    """Incrementally remove secrets without retaining unbounded raw values."""

    def __init__(self, known_secrets: tuple[str, ...] = ()) -> None:
        self._structured = _StructuredSecretRedactor()
        self._sk_tokens = _SkTokenRedactor()
        self._known = _KnownSecretRedactor(known_secrets)

    def feed(self, chunk: bytes) -> bytes:
        structured = self._structured.feed(chunk)
        tokens = self._sk_tokens.feed(structured)
        return self._known.feed(tokens)

    def finish(self) -> bytes:
        structured = self._structured.finish()
        tokens = self._sk_tokens.feed(structured) + self._sk_tokens.finish()
        return self._known.feed(tokens) + self._known.finish()


class _StructuredSecretRedactor:
    def __init__(self) -> None:
        self._mode = "normal"
        self._word_tail = bytearray()
        self._after_word_space = False
        self._quote: int | None = None
        self._escaped = False
        self._mapping_depth = 0
        self._last_significant: int | None = None
        self._quoted_field: bytes | None = None
        self._key_buffer = bytearray()
        self._key_valid = False

    def feed(self, chunk: bytes) -> bytes:
        output = bytearray()
        for byte in chunk:
            self._consume(byte, output)
        return bytes(output)

    def finish(self) -> bytes:
        return b""

    def _consume(self, byte: int, output: bytearray) -> None:
        if self._mode == "line":
            if byte in b"\r\n":
                self._mode = "normal"
                output.append(byte)
            return
        if self._mode == "quoted":
            if self._escaped:
                self._escaped = False
            elif byte == ord("\\"):
                self._escaped = True
            elif byte == self._quote:
                self._mode = "normal"
            return
        if self._mode == "key_quote":
            output.append(byte)
            if self._escaped:
                self._escaped = False
                self._key_valid = False
            elif byte == ord("\\"):
                self._escaped = True
                self._key_valid = False
            elif byte == self._quote:
                self._mode = "normal"
                self._quoted_field = bytes(self._key_buffer).lower() if self._key_valid else None
                self._last_significant = byte
            elif byte in _TOKEN_BYTES and self._key_valid:
                self._key_buffer.append(byte)
                if len(self._key_buffer) > 32:
                    del self._key_buffer[:-32]
            else:
                self._key_valid = False
            return
        if self._mode == "unquoted":
            if byte in _VALUE_DELIMITERS:
                self._mode = "normal"
                self._consume_normal(byte, output)
            return
        if self._mode == "await_value":
            if byte in b" \t":
                return
            if byte in b"'\"":
                self._quote = byte
                self._escaped = False
                self._mode = "quoted"
                return
            if byte in _VALUE_DELIMITERS:
                self._mode = "normal"
                self._consume_normal(byte, output)
                return
            self._mode = "unquoted"
            return
        self._consume_normal(byte, output)

    def _consume_normal(self, byte: int, output: bytearray) -> None:
        word = bytes(self._word_tail).lower()
        field = self._quoted_field if self._quoted_field is not None else word
        if byte in b"=":
            output.append(byte)
            if field == b"authorization":
                output.extend(_REDACTED)
                self._mode = "line"
            elif _is_sensitive_field(field):
                output.extend(_REDACTED)
                self._mode = "await_value"
            self._word_tail.clear()
            self._quoted_field = None
            self._after_word_space = False
            self._last_significant = byte
            return
        if byte == ord(":"):
            output.append(byte)
            if field == b"authorization":
                output.extend(_REDACTED)
                self._mode = "line"
            elif _is_sensitive_field(field):
                output.extend(_REDACTED)
                self._mode = "await_value"
            self._word_tail.clear()
            self._quoted_field = None
            self._after_word_space = False
            self._last_significant = byte
            return
        if byte in b" \t":
            output.append(byte)
            if word == b"bearer":
                output.extend(_REDACTED)
                self._mode = "await_value"
                self._word_tail.clear()
            else:
                self._after_word_space = True
            return
        if byte in b"\r\n":
            output.append(byte)
            self._word_tail.clear()
            self._quoted_field = None
            self._after_word_space = False
            return

        if (
            byte in b"'\""
            and self._mapping_depth > 0
            and self._last_significant in (ord("{"), ord(","))
        ):
            output.append(byte)
            self._mode = "key_quote"
            self._quote = byte
            self._escaped = False
            self._key_buffer.clear()
            self._key_valid = True
            self._word_tail.clear()
            self._after_word_space = False
            return

        output.append(byte)
        if self._quoted_field is not None:
            self._quoted_field = None
        if self._after_word_space:
            self._word_tail.clear()
            self._after_word_space = False
        if byte in _TOKEN_BYTES:
            self._word_tail.append(byte)
            if len(self._word_tail) > 32:
                del self._word_tail[:-32]
        else:
            self._word_tail.clear()
        if byte == ord("{"):
            self._mapping_depth += 1
        elif byte == ord("}"):
            self._mapping_depth = max(0, self._mapping_depth - 1)
        self._last_significant = byte


class _SkTokenRedactor:
    def __init__(self) -> None:
        self._candidate = bytearray()
        self._suppressing = False
        self._previous_is_alnum = False

    def feed(self, chunk: bytes) -> bytes:
        output = bytearray()
        for byte in chunk:
            self._consume(byte, output)
        return bytes(output)

    def finish(self) -> bytes:
        remaining = bytes(self._candidate)
        self._candidate.clear()
        if remaining:
            self._previous_is_alnum = _is_ascii_alnum(remaining[-1])
        return remaining

    def _consume(self, byte: int, output: bytearray) -> None:
        if self._suppressing:
            if byte in _TOKEN_BYTES:
                return
            self._suppressing = False
            self._consume(byte, output)
            return

        expected = (ord("s"), ord("k"), ord("-"))
        if len(self._candidate) < 3:
            if not self._candidate and (byte | 32 != ord("s") or self._previous_is_alnum):
                self._emit_safe(bytes((byte,)), output)
                return
            wanted = expected[len(self._candidate)]
            if byte | 32 == wanted:
                self._candidate.append(byte)
                return
            if self._candidate:
                self._emit_safe(bytes(self._candidate), output)
                self._candidate.clear()
                self._consume(byte, output)
                return

        if byte not in _TOKEN_BYTES:
            self._emit_safe(bytes(self._candidate), output)
            self._candidate.clear()
            self._consume(byte, output)
            return
        self._candidate.append(byte)
        if len(self._candidate) == 11:
            output.extend(_REDACTED)
            self._candidate.clear()
            self._suppressing = True

    def _emit_safe(self, value: bytes, output: bytearray) -> None:
        output.extend(value)
        if value:
            self._previous_is_alnum = _is_ascii_alnum(value[-1])


class _KnownSecretRedactor:
    def __init__(self, known_secrets: tuple[str, ...]) -> None:
        self._patterns = tuple(
            sorted(
                {secret.encode("utf-8").lower() for secret in known_secrets if secret},
                key=len,
            )
        )
        self._pending = bytearray()

    def feed(self, chunk: bytes) -> bytes:
        if not self._patterns:
            return chunk
        output = bytearray()
        for byte in chunk:
            self._pending.append(byte)
            self._release(output, final=False)
        return bytes(output)

    def finish(self) -> bytes:
        output = bytearray()
        self._release(output, final=True)
        return bytes(output)

    def _release(self, output: bytearray, *, final: bool) -> None:
        while self._pending:
            folded = bytes(self._pending).lower()
            prefixes = tuple(pattern for pattern in self._patterns if pattern.startswith(folded))
            if prefixes and not final:
                if folded in self._patterns and not any(
                    len(pattern) > len(folded) for pattern in prefixes
                ):
                    output.extend(_REDACTED)
                    self._pending.clear()
                return

            exact_prefixes = tuple(
                pattern for pattern in self._patterns if folded.startswith(pattern)
            )
            if exact_prefixes:
                longest = max(exact_prefixes, key=len)
                output.extend(_REDACTED)
                del self._pending[: len(longest)]
                continue
            output.append(self._pending.pop(0))


def _is_sensitive_field(word: bytes) -> bool:
    canonical = word.replace(b"-", b"_")
    return any(
        canonical == suffix or canonical.endswith(b"_" + suffix) for suffix in _SENSITIVE_SUFFIXES
    )


def _is_ascii_alnum(byte: int) -> bool:
    return ord("0") <= byte <= ord("9") or ord("a") <= (byte | 32) <= ord("z")


class FeedbackEngine:
    def __init__(self, output_tail_chars: int, known_secrets: tuple[str, ...] = ()) -> None:
        if type(output_tail_chars) is not int or output_tail_chars <= 0:
            raise ValueError("output_tail_chars must be a positive integer")
        self._output_tail_chars = output_tail_chars
        self._known_secrets = tuple(secret for secret in known_secrets if secret)

    def from_test(self, result: TestResult) -> Feedback:
        combined = _combine_output(result.stdout, result.stderr)
        kind = _classify(result, combined)
        node_id_candidates = set(result.failed_tests).union(_NODE_ID_PATTERN.findall(combined))
        failed_tests = tuple(
            sorted(node_id for node_id in node_id_candidates if self._is_safe_node_id(node_id))
        )
        safe_output = _INTERNAL_MARKER_PATTERN.sub("", self._redact(combined))
        feedback = Feedback(
            kind=kind,
            passed=kind is FeedbackKind.PASSED,
            exit_code=result.exit_code,
            summary=_SUMMARY_BY_KIND[kind],
            failed_tests=failed_tests,
            output_tail=safe_output[-self._output_tail_chars :],
        )
        return replace(feedback, fingerprint=fingerprint(feedback))

    def from_policy(self, decision: PolicyDecision) -> Feedback:
        if decision.level is not PolicyLevel.DENY:
            raise ValueError("policy feedback requires a denied decision")
        feedback = Feedback(
            kind=FeedbackKind.POLICY_DENIED,
            passed=None,
            exit_code=None,
            summary=f"Policy decision was {decision.level.value}.",
        )
        return replace(feedback, fingerprint=fingerprint(feedback))

    def from_tool(self, observation: Observation) -> Feedback:
        if observation.success:
            raise ValueError("tool feedback requires a failed observation")
        feedback = Feedback(
            kind=FeedbackKind.TOOL_ERROR,
            passed=None,
            exit_code=observation.exit_code,
            summary="Tool execution failed.",
        )
        return replace(feedback, fingerprint=fingerprint(feedback))

    def _redact(self, text: str) -> str:
        redactor = OutputRedactor(self._known_secrets)
        payload = text.encode("utf-8", errors="replace")
        safe = (redactor.feed(payload) + redactor.finish()).decode("utf-8", errors="replace")
        safe = _WINDOWS_PATH_PATTERN.sub("[PATH]", safe)
        return _POSIX_PATH_PATTERN.sub("[PATH]", safe)

    def _is_safe_node_id(self, node_id: str) -> bool:
        if not _NODE_ID_FULL_PATTERN.fullmatch(node_id):
            return False
        path = node_id.split("::", 1)[0]
        if path.startswith(("/", "\\")) or re.match(r"(?i)^[a-z]:", path):
            return False
        segments = re.split(r"[\\/]", path)
        if any(segment in {"", ".", ".."} for segment in segments):
            return False
        return self._redact(node_id) == node_id


def fingerprint(feedback: Feedback) -> str:
    canonical = {
        "kind": feedback.kind.value,
        "exit_code": feedback.exit_code,
        "failed_tests": sorted(set(feedback.failed_tests)),
        "summary": " ".join(feedback.summary.split()),
    }
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _combine_output(stdout: str, stderr: str) -> str:
    if stdout and stderr:
        return f"{stdout}\n{stderr}"
    return stdout or stderr


def _classify(result: TestResult, combined: str) -> FeedbackKind:
    if result.timed_out:
        return FeedbackKind.TIMEOUT
    folded = combined.casefold()
    if (
        "[fbw_diagnostic:collection]" in folded
        or "error collecting" in folded
        or "error during collection" in folded
    ):
        return FeedbackKind.COLLECTION_FAILURE
    if "[fbw_diagnostic:syntax]" in folded or "syntaxerror" in folded:
        return FeedbackKind.SYNTAX_ERROR
    if (
        "[fbw_diagnostic:import]" in folded
        or "importerror" in folded
        or "modulenotfounderror" in folded
    ):
        return FeedbackKind.IMPORT_ERROR
    if (
        "[fbw_diagnostic:assertion]" in folded
        or "assertionerror" in folded
        or re.search(r"(?m)^FAILED\s+", combined)
    ):
        return FeedbackKind.ASSERTION_FAILURE
    if result.exit_code != 0:
        return FeedbackKind.UNKNOWN_TEST_FAILURE
    return FeedbackKind.PASSED
