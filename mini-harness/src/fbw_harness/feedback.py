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
_AUTHORIZATION_PATTERN = re.compile(r"(?i)\bauthorization\b\s*[:=]\s*(?:basic|bearer)?\s*[^\s,;]+")
_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?:api[ _-]?key|(?:[a-z0-9]+_)*(?:key|secret|password|token))\b"
    r"\s*[:=]\s*"
    r"(?:['\"][^'\"\r\n]*['\"]|[^\s,;]+)"
)
_SK_PATTERN = re.compile(r"(?i)(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{8,}\b")

_SUMMARY_BY_KIND = {
    FeedbackKind.PASSED: "Pytest passed.",
    FeedbackKind.ASSERTION_FAILURE: "Pytest reported an assertion failure.",
    FeedbackKind.COLLECTION_FAILURE: "Pytest failed while collecting tests.",
    FeedbackKind.SYNTAX_ERROR: "Pytest reported a syntax error.",
    FeedbackKind.IMPORT_ERROR: "Pytest reported an import error.",
    FeedbackKind.TIMEOUT: "Pytest exceeded the configured timeout.",
    FeedbackKind.UNKNOWN_TEST_FAILURE: "Pytest failed for an unknown reason.",
}


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
        safe_output = self._redact(combined)
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
        safe = text
        for secret in sorted(self._known_secrets, key=len, reverse=True):
            safe = re.sub(re.escape(secret), "[REDACTED]", safe, flags=re.IGNORECASE)
        safe = _AUTHORIZATION_PATTERN.sub("Authorization: [REDACTED]", safe)
        safe = _ASSIGNMENT_PATTERN.sub("secret=[REDACTED]", safe)
        safe = _SK_PATTERN.sub("[REDACTED]", safe)
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
    if "error collecting" in folded or "error during collection" in folded:
        return FeedbackKind.COLLECTION_FAILURE
    if "syntaxerror" in folded:
        return FeedbackKind.SYNTAX_ERROR
    if "importerror" in folded or "modulenotfounderror" in folded:
        return FeedbackKind.IMPORT_ERROR
    if "assertionerror" in folded or re.search(r"(?m)^FAILED\s+", combined):
        return FeedbackKind.ASSERTION_FAILURE
    if result.exit_code != 0:
        return FeedbackKind.UNKNOWN_TEST_FAILURE
    return FeedbackKind.PASSED
