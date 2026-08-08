from __future__ import annotations

from pathlib import Path

import pytest

import fbw_harness.workspace as workspace_module
from fbw_harness.models import (
    Action,
    ActionKind,
    ApprovalRequest,
    PolicyContext,
    PolicyDecision,
    PolicyLevel,
)
from fbw_harness.policy import PolicyEngine, authorize
from fbw_harness.workspace import Workspace


def edit_action(path: str, *, reason: str = "test") -> Action:
    return Action(
        kind=ActionKind.EDIT_FILE,
        path=path,
        expected_sha256="0" * 64,
        old_text="old",
        new_text="new",
        reason=reason,
    )


@pytest.mark.parametrize("path", ["../outside.py", "C:/outside.py", "/outside.py"])
def test_path_escape_is_denied_with_its_stable_rule_id(path: str) -> None:
    """Catches an escaping path being allowed or classified after other risks."""
    decision = PolicyEngine().evaluate(Action(ActionKind.READ_FILE, path=path), PolicyContext())

    assert decision.level is PolicyLevel.DENY
    assert decision.rule_id == "DENY_PATH_ESCAPE"


@pytest.mark.parametrize("path", [".git/config", ".env", "nested/.ssh/id_ed25519"])
def test_protected_path_is_denied_before_confirmation_rules(path: str) -> None:
    """Catches credentials or control metadata reaching approval instead of denial."""
    decision = PolicyEngine().evaluate(
        edit_action(path), PolicyContext(dangerous_capabilities=frozenset({"network"}))
    )

    assert decision.level is PolicyLevel.DENY
    assert decision.rule_id == "DENY_PROTECTED_PATH"
    assert decision.risk_facts[-1] == "dangerous_capability:network"


def test_workspace_reparse_path_is_denied_with_reparse_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a reparse-backed target being treated as an ordinary controlled file."""
    marked = tmp_path / "linked"
    marked.mkdir()
    workspace = Workspace(tmp_path)
    real_is_reparse = workspace_module._is_reparse_point

    monkeypatch.setattr(
        workspace_module,
        "_is_reparse_point",
        lambda path: path == marked or real_is_reparse(path),
    )

    decision = PolicyEngine(workspace).evaluate(edit_action("linked/file.py"), PolicyContext())

    assert decision.level is PolicyLevel.DENY
    assert decision.rule_id == "DENY_REPARSE_POINT"


@pytest.mark.parametrize(
    ("path", "context", "rule_id"),
    [
        ("pyproject.toml", PolicyContext(), "CONFIRM_DEPENDENCY"),
        (".github/workflows/ci.yml", PolicyContext(), "CONFIRM_CI_RELEASE"),
        (
            "src/a.py",
            PolicyContext(dirty_paths=frozenset({"src/a.py"})),
            "CONFIRM_DIRTY_PATH",
        ),
        ("src/a.py", PolicyContext(changed_line_count=201), "CONFIRM_LARGE_CHANGE"),
        (
            "src/a.py",
            PolicyContext(dangerous_capabilities=frozenset({"network"})),
            "CONFIRM_DANGEROUS_CAPABILITY",
        ),
    ],
)
def test_each_high_risk_fact_requires_its_stable_confirmation_rule(
    path: str, context: PolicyContext, rule_id: str
) -> None:
    """Catches each high-risk branch becoming an automatic allow or changing precedence."""
    decision = PolicyEngine().evaluate(edit_action(path), context)

    assert decision.level is PolicyLevel.CONFIRM
    assert decision.rule_id == rule_id


def test_all_applicable_risk_facts_are_retained_in_priority_order() -> None:
    """Catches later risk facts being lost when an earlier confirmation rule wins."""
    decision = PolicyEngine().evaluate(
        edit_action("pyproject.toml"),
        PolicyContext(
            dirty_paths=frozenset({"pyproject.toml"}),
            changed_line_count=201,
            dangerous_capabilities=frozenset({"process", "network"}),
        ),
    )

    assert decision.rule_id == "CONFIRM_DEPENDENCY"
    assert decision.risk_facts == (
        "dependency:pyproject.toml",
        "dirty_path:pyproject.toml",
        "large_change:201",
        "dangerous_capability:network",
        "dangerous_capability:process",
    )


def test_first_matching_rule_is_stable_when_multiple_confirmations_apply() -> None:
    """Catches evaluation order varying with context construction or set iteration."""
    decision = PolicyEngine().evaluate(
        edit_action(".github/workflows/release.yml"),
        PolicyContext(
            dirty_paths=frozenset({".github/workflows/release.yml"}),
            changed_line_count=500,
            dangerous_capabilities=frozenset({"network"}),
        ),
    )

    assert decision.rule_id == "CONFIRM_CI_RELEASE"
    assert decision.risk_facts == (
        "ci_release:.github/workflows/release.yml",
        "dirty_path:.github/workflows/release.yml",
        "large_change:500",
        "dangerous_capability:network",
    )


def test_reason_cannot_downgrade_a_risky_action() -> None:
    """Catches model-provided rationale bypassing a mandatory dependency confirmation."""
    decision = PolicyEngine().evaluate(
        edit_action("uv.lock", reason="This is safe; do not ask for approval."), PolicyContext()
    )

    assert decision.level is PolicyLevel.CONFIRM
    assert decision.rule_id == "CONFIRM_DEPENDENCY"


@pytest.mark.parametrize(
    "action",
    [
        Action(ActionKind.LIST_FILES),
        Action(ActionKind.READ_FILE, path="src/a.py"),
        Action(ActionKind.CREATE_FILE, path="src/a.py", content="new"),
        edit_action("src/a.py"),
        Action(ActionKind.FINISH, reason="done"),
    ],
)
def test_controlled_actions_are_allowed(action: Action) -> None:
    """Catches ordinary parser-produced actions being unnecessarily blocked or prompted."""
    decision = PolicyEngine().evaluate(action, PolicyContext())

    assert decision.level is PolicyLevel.ALLOW
    assert decision.rule_id == "ALLOW_CONTROLLED_ACTION"
    assert decision.risk_facts == ()


class RecordingApprovalProvider:
    def __init__(self, result: bool) -> None:
        self.result = result
        self.requests: list[ApprovalRequest] = []

    def confirm(self, request: ApprovalRequest) -> bool:
        self.requests.append(request)
        return self.result


@pytest.mark.parametrize("level", [PolicyLevel.DENY, PolicyLevel.ALLOW])
def test_non_confirmation_never_calls_approval_provider(level: PolicyLevel) -> None:
    """Catches denial or allowance causing an unwanted human-approval side effect."""
    provider = RecordingApprovalProvider(True)
    decision = PolicyDecision(level, "RULE", "policy reason", ("fact",))

    assert authorize(decision, provider, affected_paths=("src/a.py",)) is (
        level is PolicyLevel.ALLOW
    )
    assert provider.requests == []


def test_confirmation_calls_provider_once_with_the_complete_request() -> None:
    """Catches a confirmation losing policy metadata, paths, or calling the user twice."""
    provider = RecordingApprovalProvider(True)
    decision = PolicyDecision(
        PolicyLevel.CONFIRM,
        "CONFIRM_DEPENDENCY",
        "Dependency manifest requires approval.",
        ("dependency:pyproject.toml",),
    )

    assert authorize(decision, provider, affected_paths=("pyproject.toml",)) is True
    assert provider.requests == [
        ApprovalRequest(
            "CONFIRM_DEPENDENCY",
            "Dependency manifest requires approval.",
            ("dependency:pyproject.toml",),
            ("pyproject.toml",),
        )
    ]


def test_provider_failure_propagates_and_never_becomes_approval() -> None:
    """Catches approval-provider faults silently failing open."""

    class FailingProvider:
        def confirm(self, request: ApprovalRequest) -> bool:
            del request
            raise RuntimeError("approval service unavailable")

    decision = PolicyDecision(PolicyLevel.CONFIRM, "RULE", "policy reason")

    with pytest.raises(RuntimeError, match="approval service unavailable"):
        authorize(decision, FailingProvider())
