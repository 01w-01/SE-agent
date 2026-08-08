from __future__ import annotations

from pathlib import PurePosixPath

from .models import Action, ApprovalRequest, PolicyContext, PolicyDecision, PolicyLevel
from .ports import ApprovalProvider
from .workspace import PolicyDeniedError, Workspace, _is_protected_name, _relative_parts

_DEPENDENCY_BASENAMES = frozenset(
    {
        "pyproject.toml",
        "uv.lock",
        "package.json",
        "package-lock.json",
        "npm-shrinkwrap.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "bun.lockb",
        "pipfile",
        "pipfile.lock",
        "poetry.lock",
        "setup.py",
        "setup.cfg",
        "cargo.toml",
        "cargo.lock",
        "go.mod",
        "go.sum",
        "gemfile",
        "gemfile.lock",
        "composer.json",
        "composer.lock",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "gradle.lockfile",
        "deno.json",
        "deno.jsonc",
        "deno.lock",
        "bun.lock",
    }
)
_CI_RELEASE_BASENAMES = frozenset(
    {
        ".gitlab-ci.yml",
        ".travis.yml",
        "appveyor.yml",
        "azure-pipelines.yml",
        "bitbucket-pipelines.yml",
        "cloudbuild.yaml",
        "cloudbuild.yml",
        "jenkinsfile",
        "release.yml",
        "release.yaml",
        "workflow.yml",
        "workflow.yaml",
        "build.yml",
        "build.yaml",
    }
)
_DANGEROUS_CAPABILITIES = frozenset(
    {"network", "process", "registry", "dependency", "ci", "release"}
)


class PolicyEngine:
    """Classify parser-produced actions without executing or approving them."""

    def __init__(
        self, workspace: Workspace | None = None, normal_change_line_limit: int = 200
    ) -> None:
        if type(normal_change_line_limit) is not int or normal_change_line_limit <= 0:
            raise ValueError("normal_change_line_limit must be a positive integer")
        self._workspace = workspace
        self._normal_change_line_limit = normal_change_line_limit

    def evaluate(self, action: Action, context: PolicyContext) -> PolicyDecision:
        """Return the first matching rule while retaining every sanitized risk fact."""
        facts: list[tuple[str, str]] = []
        normalized_path: str | None = None

        if action.path is not None:
            normalized_path, escapes = _normalize_path(action.path)
            if escapes:
                facts.append(("DENY_PATH_ESCAPE", "path_escape"))
                facts.extend(_invalid_path_facts(action.path))
            else:
                if _has_protected_segment(normalized_path):
                    facts.append(("DENY_PROTECTED_PATH", f"protected_path:{normalized_path}"))
                elif self._workspace is not None and not _workspace_path_is_safe(
                    self._workspace, action.path
                ):
                    facts.append(("DENY_REPARSE_POINT", "reparse_point"))

                if _is_dependency_path(normalized_path):
                    facts.append(("CONFIRM_DEPENDENCY", f"dependency:{normalized_path}"))
                if _is_ci_or_release_path(normalized_path):
                    facts.append(("CONFIRM_CI_RELEASE", f"ci_release:{normalized_path}"))
                if _is_dirty_path(normalized_path, context.dirty_paths):
                    facts.append(("CONFIRM_DIRTY_PATH", f"dirty_path:{normalized_path}"))

        if action.path is not None and context.changed_line_count > self._normal_change_line_limit:
            facts.append(("CONFIRM_LARGE_CHANGE", f"large_change:{context.changed_line_count}"))

        for capability in _sanitize_capabilities(context.dangerous_capabilities):
            facts.append(("CONFIRM_DANGEROUS_CAPABILITY", f"dangerous_capability:{capability}"))

        if facts:
            rule_id = facts[0][0]
            level = _level_for_rule(rule_id)
            return PolicyDecision(
                level, rule_id, _reason_for_rule(rule_id), tuple(fact for _, fact in facts)
            )
        return PolicyDecision(
            PolicyLevel.ALLOW,
            "ALLOW_CONTROLLED_ACTION",
            "Action is within the controlled workspace policy.",
        )


def authorize(
    decision: PolicyDecision,
    provider: ApprovalProvider,
    *,
    affected_paths: tuple[str, ...] = (),
) -> bool:
    """Return the policy outcome, calling the approval port only for confirmations."""
    if decision.level is PolicyLevel.DENY:
        return False
    if decision.level is PolicyLevel.ALLOW:
        return True
    request = ApprovalRequest(
        decision.rule_id,
        decision.reason,
        decision.risk_facts,
        affected_paths,
    )
    return provider.confirm(request)


def _normalize_path(path: str) -> tuple[str | None, bool]:
    try:
        return "/".join(_relative_parts(path)), False
    except PolicyDeniedError:
        return None, True


def _has_protected_segment(path: str) -> bool:
    return any(_is_protected_name(part) for part in PurePosixPath(path).parts)


def _invalid_path_facts(path: str) -> list[tuple[str, str]]:
    """Retain fixed, non-secret facts when the canonical path checker rejects input."""
    parts = tuple(part for part in path.replace("\\", "/").split("/") if part)
    facts: list[tuple[str, str]] = []
    if any(_is_protected_name(part) for part in parts):
        facts.append(("DENY_PROTECTED_PATH", "protected_path"))
    if parts and _is_dependency_basename(parts[-1]):
        facts.append(("CONFIRM_DEPENDENCY", "dependency_manifest"))
    if _is_ci_or_release_parts(parts):
        facts.append(("CONFIRM_CI_RELEASE", "ci_release_config"))
    return facts


def _workspace_path_is_safe(workspace: Workspace, path: str) -> bool:
    try:
        workspace.resolve_safe(path, must_exist=False)
    except PolicyDeniedError:
        return False
    return True


def _is_dependency_path(path: str) -> bool:
    return _is_dependency_basename(PurePosixPath(path).name)


def _is_dependency_basename(basename: str) -> bool:
    canonical = basename.casefold()
    return canonical in _DEPENDENCY_BASENAMES or (
        canonical.startswith("requirements") and canonical.endswith(".txt")
    )


def _is_ci_or_release_path(path: str) -> bool:
    return _is_ci_or_release_parts(PurePosixPath(path).parts)


def _is_ci_or_release_parts(parts: tuple[str, ...]) -> bool:
    if not parts:
        return False
    canonical_parts = tuple(part.casefold() for part in parts)
    basename = canonical_parts[-1]
    return ".github" in canonical_parts or basename in _CI_RELEASE_BASENAMES


def _is_dirty_path(path: str, dirty_paths: frozenset[str]) -> bool:
    return path.casefold() in {
        normalized.casefold()
        for dirty_path in dirty_paths
        for normalized, escaped in (_normalize_path(dirty_path),)
        if not escaped and normalized is not None
    }


def _sanitize_capabilities(capabilities: frozenset[str]) -> tuple[str, ...]:
    known: set[str] = set()
    unknown = False
    for capability in capabilities:
        if not isinstance(capability, str):
            unknown = True
            continue
        canonical = capability.strip().casefold()
        if canonical in _DANGEROUS_CAPABILITIES:
            known.add(canonical)
        else:
            unknown = True
    if unknown:
        known.add("unknown")
    return tuple(sorted(known))


def _level_for_rule(rule_id: str) -> PolicyLevel:
    if rule_id.startswith("DENY_"):
        return PolicyLevel.DENY
    return PolicyLevel.CONFIRM


def _reason_for_rule(rule_id: str) -> str:
    reasons = {
        "DENY_PATH_ESCAPE": "Path escapes the controlled workspace.",
        "DENY_PROTECTED_PATH": "Path targets protected workspace metadata or credentials.",
        "DENY_REPARSE_POINT": "Path cannot be resolved without crossing a reparse point.",
        "CONFIRM_DEPENDENCY": "Dependency or lock-file changes require approval.",
        "CONFIRM_CI_RELEASE": "CI, workflow, or release changes require approval.",
        "CONFIRM_DIRTY_PATH": "Action targets a path already dirty at task start.",
        "CONFIRM_LARGE_CHANGE": "Change exceeds the normal line-change limit.",
        "CONFIRM_DANGEROUS_CAPABILITY": "Action context includes a dangerous capability.",
    }
    return reasons[rule_id]
