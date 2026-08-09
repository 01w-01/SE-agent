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
_MAX_CONTAINER_DEPTH = 64
_MAX_FIELD_TAIL = 64
_SENSITIVE_SUFFIXES = (b"key", b"secret", b"password", b"token")
_MAPPING_VALUE_DELIMITERS = frozenset(b" \t\r\n,}]")
_GLOBAL_VALUE_DELIMITERS = frozenset(b" \t\r\n,;'\"}]")
_FIELD_BYTES = frozenset(b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-. \t")
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
        self._mapping = _MappingSecretRedactor()
        self._global = _GlobalSecretRedactor()
        self._sk_tokens = _SkTokenRedactor()
        self._known = _KnownSecretRedactor(known_secrets)

    def feed(self, chunk: bytes) -> bytes:
        mapped = self._mapping.feed(chunk)
        globally_safe = self._global.feed(mapped)
        tokens = self._sk_tokens.feed(globally_safe)
        return self._known.feed(tokens)

    def finish(self) -> bytes:
        mapped = self._mapping.finish()
        globally_safe = self._global.feed(mapped) + self._global.finish()
        tokens = self._sk_tokens.feed(globally_safe) + self._sk_tokens.finish()
        return self._known.feed(tokens) + self._known.finish()


class _MappingSecretRedactor:
    """Associate quoted mapping keys with values using bounded parser state."""

    def __init__(self) -> None:
        self._mode = "normal"
        self._containers: list[int] = []
        self._last_significant: int | None = None
        self._quote: int | None = None
        self._escaped = False
        self._string_is_key = False
        self._key_buffer = bytearray()
        self._key_valid = False
        self._key_suspicious = False
        self._pending_key: bytes | None = None
        self._pending_key_suspicious = False

    def feed(self, chunk: bytes) -> bytes:
        output = bytearray()
        for byte in chunk:
            self._consume(byte, output)
        return bytes(output)

    def finish(self) -> bytes:
        return b""

    def _consume(self, byte: int, output: bytearray) -> None:
        if self._mode == "suppress_rest":
            return
        if self._mode == "suppress_quoted":
            if self._escaped:
                self._escaped = False
            elif byte == ord("\\"):
                self._escaped = True
            elif byte == self._quote:
                self._mode = "normal"
                self._last_significant = byte
            return
        if self._mode == "suppress_unquoted":
            if byte in _MAPPING_VALUE_DELIMITERS:
                self._mode = "normal"
                self._consume_normal(byte, output)
            return
        if self._mode == "await_value":
            if byte in b" \t":
                return
            if byte in b"'\"":
                self._quote = byte
                self._escaped = False
                self._mode = "suppress_quoted"
                return
            if byte in _MAPPING_VALUE_DELIMITERS:
                self._mode = "normal"
                self._consume_normal(byte, output)
                return
            self._mode = "suppress_unquoted"
            return
        if self._mode == "string":
            output.append(byte)
            if self._escaped:
                self._escaped = False
            elif byte == ord("\\"):
                self._escaped = True
                if self._string_is_key:
                    self._key_suspicious = True
            elif byte == self._quote:
                self._mode = "normal"
                if self._string_is_key:
                    self._pending_key = bytes(self._key_buffer) if self._key_valid else None
                    self._pending_key_suspicious = self._key_suspicious
                self._last_significant = byte
            elif self._string_is_key:
                self._consume_key_byte(byte)
            return
        self._consume_normal(byte, output)

    def _consume_normal(self, byte: int, output: bytearray) -> None:
        if byte in b"{[" and len(self._containers) >= _MAX_CONTAINER_DEPTH:
            output.extend(_REDACTED)
            self._containers.clear()
            self._mode = "suppress_rest"
            return

        if byte == ord(":"):
            output.append(byte)
            sensitive = self._pending_key_suspicious or (
                self._pending_key is not None and _is_sensitive_mapping_key(self._pending_key)
            )
            if sensitive:
                output.extend(_REDACTED)
                self._mode = "await_value"
            self._clear_pending_key()
            self._last_significant = byte
            return
        if byte in b" \t\r\n":
            output.append(byte)
            return

        if byte in b"'\"":
            is_key = bool(
                self._containers
                and self._containers[-1] == ord("{")
                and self._last_significant in (ord("{"), ord(","))
            )
            if not is_key:
                self._clear_pending_key()
            output.append(byte)
            self._mode = "string"
            self._quote = byte
            self._escaped = False
            self._string_is_key = is_key
            self._key_buffer.clear()
            self._key_valid = True
            self._key_suspicious = False
            return

        self._clear_pending_key()
        output.append(byte)
        if byte in b"{[":
            self._containers.append(byte)
        elif self._containers and (
            (byte == ord("}") and self._containers[-1] == ord("{"))
            or (byte == ord("]") and self._containers[-1] == ord("["))
        ):
            self._containers.pop()
        self._last_significant = byte

    def _consume_key_byte(self, byte: int) -> None:
        if not self._key_valid:
            return
        if _is_ascii_alnum(byte):
            canonical = byte | 32
        elif byte in b" .-_":
            canonical = ord("_")
        else:
            self._key_valid = False
            return
        self._key_buffer.append(canonical)
        if len(self._key_buffer) > _MAX_FIELD_TAIL:
            del self._key_buffer[:-_MAX_FIELD_TAIL]

    def _clear_pending_key(self) -> None:
        self._pending_key = None
        self._pending_key_suspicious = False


class _GlobalSecretRedactor:
    """Scan every mapped byte for secret-bearing assignments."""

    def __init__(self) -> None:
        self._mode = "normal"
        self._candidate = bytearray()
        self._quote: int | None = None
        self._escaped = False

    def feed(self, chunk: bytes) -> bytes:
        output = bytearray()
        for byte in chunk:
            self._consume(byte, output)
        return bytes(output)

    def finish(self) -> bytes:
        output = bytearray()
        if self._mode == "normal":
            self._flush_candidate(output)
        else:
            self._candidate.clear()
        return bytes(output)

    def _consume(self, byte: int, output: bytearray) -> None:
        if self._mode == "line":
            if byte in b"\r\n":
                self._mode = "normal"
                output.append(byte)
            return
        if self._mode == "suppress_quoted":
            if self._escaped:
                self._escaped = False
            elif byte == ord("\\"):
                self._escaped = True
            elif byte == self._quote:
                self._mode = "normal"
                output.append(byte)
            return
        if self._mode == "suppress_unquoted":
            if byte in _GLOBAL_VALUE_DELIMITERS:
                self._mode = "normal"
                self._consume_normal(byte, output)
            return
        if self._mode == "await_value":
            if byte in b" \t":
                output.append(byte)
                return
            if byte in b"'\"":
                self._quote = byte
                self._escaped = False
                self._mode = "suppress_quoted"
                return
            if byte in _GLOBAL_VALUE_DELIMITERS:
                self._mode = "normal"
                self._consume_normal(byte, output)
                return
            self._mode = "suppress_unquoted"
            return
        self._consume_normal(byte, output)

    def _consume_normal(self, byte: int, output: bytearray) -> None:
        if byte in b"\r\n":
            self._flush_candidate(output)
            output.append(byte)
            return
        if byte in b"=:":
            canonical = _canonical_field(bytes(self._candidate))
            authorization = canonical == b"authorization" or canonical.endswith(b"_authorization")
            sensitive = authorization or _is_sensitive_field(canonical)
            self._flush_candidate(output)
            output.append(byte)
            if sensitive:
                output.extend(_REDACTED)
                self._mode = "line" if authorization else "await_value"
            return
        if byte in _FIELD_BYTES:
            if byte in b" \t" and _is_bearer_field(_canonical_field(bytes(self._candidate))):
                self._flush_candidate(output)
                output.append(byte)
                output.extend(_REDACTED)
                self._mode = "await_value"
                return
            self._candidate.append(byte)
            if len(self._candidate) > _MAX_FIELD_TAIL:
                output.append(self._candidate.pop(0))
            return
        self._flush_candidate(output)
        output.append(byte)

    def _flush_candidate(self, output: bytearray) -> None:
        output.extend(self._candidate)
        self._candidate.clear()


class _SkTokenRedactor:
    def __init__(self) -> None:
        self._candidate = bytearray()
        self._suppressing = False
        self._previous_blocks_start = False

    def feed(self, chunk: bytes) -> bytes:
        output = bytearray()
        for byte in chunk:
            self._consume(byte, output)
        return bytes(output)

    def finish(self) -> bytes:
        remaining = bytes(self._candidate)
        self._candidate.clear()
        if remaining:
            self._previous_blocks_start = _blocks_sk_start(remaining[-1])
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
            if not self._candidate and (byte | 32 != ord("s") or self._previous_blocks_start):
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
            self._previous_blocks_start = _blocks_sk_start(value[-1])


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
    canonical = _canonical_field(word)
    return any(
        canonical == suffix or canonical.endswith(b"_" + suffix) for suffix in _SENSITIVE_SUFFIXES
    )


def _is_sensitive_mapping_key(field: bytes) -> bool:
    canonical = _canonical_field(field)
    return canonical == b"authorization" or _is_sensitive_field(canonical)


def _is_bearer_field(field: bytes) -> bool:
    return field == b"bearer" or field.endswith(b"_bearer")


def _canonical_field(field: bytes) -> bytes:
    canonical = bytearray()
    previous_separator = False
    for byte in field.lower():
        if _is_ascii_alnum(byte):
            canonical.append(byte)
            previous_separator = False
        elif byte in b" .-_\t" and canonical and not previous_separator:
            canonical.append(ord("_"))
            previous_separator = True
    return bytes(canonical).strip(b"_")


def _is_ascii_alnum(byte: int) -> bool:
    return ord("0") <= byte <= ord("9") or ord("a") <= (byte | 32) <= ord("z")


def _blocks_sk_start(byte: int) -> bool:
    return _is_ascii_alnum(byte) or byte == ord("-")


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
