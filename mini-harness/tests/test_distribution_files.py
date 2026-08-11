from __future__ import annotations

import re
import subprocess
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_required_distribution_files_exist() -> None:
    """Catches a release setup that omits a required user-facing artifact."""
    root = repo_root()
    required = [
        "README.md",
        ".gitlab-ci.yml",
        ".github/workflows/release.yml",
        "mini-harness/fbw-harness.spec",
        "scripts/build.ps1",
    ]
    assert [path for path in required if not (root / path).is_file()] == []


def test_gitlab_has_exact_unit_test_job() -> None:
    """Catches CI losing the test job that validates the distributed source."""
    text = (repo_root() / ".gitlab-ci.yml").read_text(encoding="utf-8")
    assert re.search(r"(?m)^unit-test:\s*$", text)
    assert "uv run --project mini-harness pytest" in text


def test_history_scan_reports_only_locations_and_blocks_known_history() -> None:
    """Catches history scanning that leaks a matching credential or ignores a match."""
    root = repo_root()
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(root / "scripts/scan-history.ps1")],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "sk-" not in result.stdout
    assert "sk-" not in result.stderr
    assert result.stderr == ""
