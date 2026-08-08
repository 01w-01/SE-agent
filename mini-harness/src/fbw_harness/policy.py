from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath

from .models import Action, ApprovalRequest, PolicyContext, PolicyDecision, PolicyLevel
from .ports import ApprovalProvider
from .workspace import PolicyDeniedError, Workspace

_PROTECTED_EXACT_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "node_modules",
        ".fbw-recovery",
        ".credentials",
        ".secrets",
        ".aws",
        ".ssh",
        ".azure",
        "build",
        "dist",
        ".eggs",
        "credentials.json",
    }
)
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
    }
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
        normalized_path = ""

        if action.path is not None:
            normalized_path, escapes = _normalize_path(action.path)
            if escapes:
                facts.append(("DENY_PATH_ESCAPE", "path_escape"))
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

        for capability in sorted(_sanitize_capabilities(context.dangerous_capabilities)):
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


def _normalize_path(path: str) -> tuple[str, bool]:
    normalized = path.replace("\\", "/")
    windows_path = PureWindowsPath(path)
    if (
        not path
        or "\x00" in path
        or windows_path.drive
        or windows_path.is_absolute()
        or normalized.startswith("/")
    ):
        return normalized, True
    parts = PurePosixPath(normalized).parts
    if not parts or any(part == ".." for part in parts):
        return normalized, True
    return "/".join(parts), False


def _has_protected_segment(path: str) -> bool:
    for part in PurePosixPath(path).parts:
        canonical = part.rstrip(" .").casefold()
        if (
            canonical in _PROTECTED_EXACT_NAMES
            or canonical.startswith(".env")
            or canonical.endswith(".egg-info")
        ):
            return True
    return False


def _workspace_path_is_safe(workspace: Workspace, path: str) -> bool:
    try:
        workspace.resolve_safe(path, must_exist=False)
    except PolicyDeniedError:
        return False
    return True


def _is_dependency_path(path: str) -> bool:
    basename = PurePosixPath(path).name.casefold()
    return basename in _DEPENDENCY_BASENAMES or (
        basename.startswith("requirements") and basename.endswith(".txt")
    )


def _is_ci_or_release_path(path: str) -> bool:
    parts = tuple(part.casefold() for part in PurePosixPath(path).parts)
    basename = parts[-1]
    return ".github" in parts or basename in _CI_RELEASE_BASENAMES


def _is_dirty_path(path: str, dirty_paths: frozenset[str]) -> bool:
    return path in {
        normalized
        for dirty_path in dirty_paths
        for normalized, escaped in (_normalize_path(dirty_path),)
        if not escaped
    }


def _sanitize_capabilities(capabilities: frozenset[str]) -> frozenset[str]:
    return frozenset(
        capability.strip().casefold() for capability in capabilities if capability.strip()
    )


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
