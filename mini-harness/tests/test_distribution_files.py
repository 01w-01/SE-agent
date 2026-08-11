from __future__ import annotations

import re
import shutil
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
    lines = [line for line in result.stdout.splitlines() if line]
    assert lines
    assert all(re.fullmatch(r"[0-9a-f]{40} [^\r\n]+", line) for line in lines)


def test_build_removes_published_artifacts_when_staging_cleanup_fails(tmp_path: Path) -> None:
    """Catches a successful package move surviving a later staging cleanup failure."""
    root = tmp_path / "repo"
    script_dir = root / "scripts"
    script_dir.mkdir(parents=True)
    shutil.copy2(repo_root() / "scripts/build.ps1", script_dir / "build.ps1")
    (root / "mini-harness").mkdir()
    driver = tmp_path / "run-build.ps1"
    driver.write_text(
        rf"""
function uv {{
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    if ($Arguments -contains "pyinstaller") {{
        $index = [array]::IndexOf($Arguments, "--distpath")
        $output = $Arguments[$index + 1]
        New-Item -ItemType Directory -Force -Path $output | Out-Null
        Set-Content -LiteralPath (Join-Path $output "fbw-harness.exe") -Value "fake"
    }}
    $global:LASTEXITCODE = 0
}}
function pwsh {{
    $global:LASTEXITCODE = 0
}}
function Remove-Item {{
    param(
        [string]$LiteralPath,
        [switch]$Force,
        [switch]$Recurse,
        [string]$ErrorAction
    )
    if ($LiteralPath -like "*.staging-*") {{
        throw "injected staging cleanup failure"
    }}
    Microsoft.PowerShell.Management\Remove-Item -LiteralPath $LiteralPath -Force:$Force -Recurse:$Recurse -ErrorAction $ErrorAction
}}
. '{(script_dir / "build.ps1").as_posix()}'
""".strip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(driver)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "injected staging cleanup failure" in result.stderr
    assert not (root / "dist/fbw-harness.exe").exists()
    assert not (root / "dist/fbw-harness.exe.sha256").exists()


def test_spec_packages_windows_keyring_fixtures_and_frozen_pytest_entrypoint() -> None:
    """Catches the one-file executable losing its credential, demo, or pytest runtime input."""
    text = (repo_root() / "mini-harness/fbw-harness.spec").read_text(encoding="utf-8")
    assert 'collect_submodules("keyring.backends.Windows")' in text
    assert 'collect_submodules("pytest")' in text
    assert 'fixture_root / "clamp.py"' in text
    assert 'fixture_root / "test_clamp.py"' in text
    assert "from fbw_harness.cli import main" in text
    assert "sys.argv[1:3]" in text


def test_github_release_waits_for_tests_and_limits_write_permission_to_tags() -> None:
    """Catches a release that can run before tests or grants push and PRs release rights."""
    text = (repo_root() / ".github/workflows/release.yml").read_text(encoding="utf-8")
    release = text.split("\n  release:\n", maxsplit=1)[1]
    assert "if: startsWith(github.ref, 'refs/tags/')" in release
    assert "needs: unit-test" in release
    assert re.search(r"(?m)^permissions:\n  contents: read$", text)
    assert re.search(r"(?m)^    permissions:\n      contents: write$", release)
