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


def test_history_scan_passes_without_leaking_output() -> None:
    """Catches a cleaned history that regains a matching credential or leaks output."""
    root = repo_root()
    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(root / "scripts/scan-history.ps1"),
            "-Revision",
            "HEAD",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_history_scan_can_limit_revision_without_weakening_default(tmp_path: Path) -> None:
    """Keeps release scans on all refs while allowing CI to verify canonical HEAD."""
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
    (root / "safe.txt").write_text("safe\n", encoding="utf-8")
    subprocess.run(["git", "add", "safe.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "safe"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "switch", "-c", "internal-old-ref"], cwd=root, check=True, capture_output=True
    )
    (root / "old.txt").write_text("sk-" + "syntheticsecret12345", encoding="utf-8")
    subprocess.run(["git", "add", "old.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "old"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "switch", "main"], cwd=root, check=True, capture_output=True)

    script = str(repo_root() / "scripts/scan-history.ps1")
    all_refs = subprocess.run(
        ["pwsh", "-NoProfile", "-File", script],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    head_only = subprocess.run(
        ["pwsh", "-NoProfile", "-File", script, "-Revision", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert all_refs.returncode == 1
    assert head_only.returncode == 0
    assert head_only.stdout == ""
    assert head_only.stderr == ""


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


def test_clean_windows_acceptance_is_manual_read_only_and_never_releases() -> None:
    """Catches clean-machine evidence gaining release rights or skipping runtime isolation."""
    root = repo_root()
    workflow = (root / ".github/workflows/clean-windows-acceptance.yml").read_text(encoding="utf-8")
    verifier = (root / "scripts/verify-clean-windows.ps1").read_text(encoding="utf-8")

    assert re.search(r"(?m)^on:\n  workflow_dispatch:\s*$", workflow)
    assert re.search(r"(?m)^permissions:\n  contents: read$", workflow)
    assert "runs-on: windows-latest" in workflow
    assert "scripts/build.ps1" in workflow
    assert "scripts/verify-clean-windows.ps1" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "softprops/action-gh-release" not in workflow
    assert "contents: write" not in workflow
    assert "fbw-clean-windows-summary.txt" in workflow

    for contract in (
        "Get-FileHash",
        "ProcessStartInfo",
        "System32",
        '"--help"',
        '"demo", "all"',
        '"credential", "status"',
        "configured=False",
        "RUNNER_TEMP",
        "finally",
    ):
        assert contract in verifier
