from __future__ import annotations

import importlib
import os
import re
import shutil
import subprocess
from pathlib import Path


def test_package_exposes_version() -> None:
    package = importlib.import_module("fbw_harness")
    assert package.__version__ == "0.1.0"


def test_tracked_worktree_has_no_api_key_pattern() -> None:
    root = Path(__file__).resolve().parents[2]
    raw_files = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
    ).stdout
    files = [path.decode("utf-8") for path in raw_files.split(b"\0") if path]
    pattern = re.compile(rb"sk-[A-Za-z0-9]{12,}")
    hits = [path for path in files if pattern.search((root / path).read_bytes())]
    assert hits == []


def test_secret_scan_fails_closed_when_git_is_unavailable(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts/scan-current-tree.ps1"
    assert script.is_file()
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(script)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.strip() == "secret scan failed"


def test_secret_scan_fails_closed_when_git_executable_is_not_on_path(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts/scan-current-tree.ps1"
    pwsh = shutil.which("pwsh")
    assert pwsh is not None
    result = subprocess.run(
        [pwsh, "-NoProfile", "-File", str(script)],
        cwd=tmp_path,
        env={**os.environ, "PATH": str(tmp_path)},
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.strip() == "secret scan failed"


def test_secret_scan_treats_no_matches_as_safe_with_native_errors_enabled() -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts/scan-current-tree.ps1"
    pwsh = shutil.which("pwsh")
    assert pwsh is not None
    command = (
        "$PSNativeCommandUseErrorActionPreference = $true; "
        f"& '{script}'; exit $LASTEXITCODE"
    )
    result = subprocess.run(
        [pwsh, "-NoProfile", "-Command", command],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
