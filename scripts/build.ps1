$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$root = Split-Path -Parent $PSScriptRoot
$project = Join-Path $root "mini-harness"
$spec = Join-Path $project "fbw-harness.spec"
$dist = Join-Path $root "dist"
$artifact = Join-Path $dist "fbw-harness.exe"
$checksum = Join-Path $dist "fbw-harness.exe.sha256"
$staging = Join-Path $dist (".staging-" + [guid]::NewGuid().ToString("N"))
$stagingDist = Join-Path $staging "dist"
$stagingWork = Join-Path $staging "work"

function Invoke-Native([scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "native command failed with exit code $LASTEXITCODE"
    }
}

function Remove-PublishedArtifacts {
    Remove-Item -LiteralPath $artifact -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $checksum -Force -ErrorAction SilentlyContinue
}

New-Item -ItemType Directory -Force -Path $dist | Out-Null
Remove-PublishedArtifacts

try {
    Invoke-Native { uv run --project $project pytest -q }
    Invoke-Native { pwsh -NoProfile -File (Join-Path $root "scripts/scan-current-tree.ps1") }
    New-Item -ItemType Directory -Force -Path $stagingDist, $stagingWork | Out-Null
    Invoke-Native {
        uv run --project $project pyinstaller --noconfirm --clean --distpath $stagingDist --workpath $stagingWork $spec
    }

    $stagedArtifact = Join-Path $stagingDist "fbw-harness.exe"
    if (-not (Test-Path -LiteralPath $stagedArtifact -PathType Leaf)) {
        throw "PyInstaller did not produce fbw-harness.exe"
    }

    Move-Item -LiteralPath $stagedArtifact -Destination $artifact -Force
    $hash = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -LiteralPath $checksum -Value "$hash  fbw-harness.exe" -Encoding utf8NoBOM -NoNewline
}
catch {
    Remove-PublishedArtifacts
    throw
}
finally {
    if (Test-Path -LiteralPath $staging) {
        try {
            Remove-Item -LiteralPath $staging -Recurse -Force
        }
        catch {
            Remove-PublishedArtifacts
            throw
        }
    }
}
