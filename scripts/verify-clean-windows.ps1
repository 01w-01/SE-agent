param(
    [Parameter(Mandatory = $true)][string]$Artifact,
    [Parameter(Mandatory = $true)][string]$Checksum,
    [Parameter(Mandatory = $true)][string]$Summary
)

$ErrorActionPreference = "Stop"

function Invoke-IsolatedExe([string]$Executable, [string[]]$Arguments, [string]$WorkingDirectory) {
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $Executable
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true
    foreach ($argument in $Arguments) {
        $startInfo.ArgumentList.Add($argument)
    }

    $systemRoot = [Environment]::GetFolderPath("Windows")
    $restrictedPath = @(
        (Join-Path $systemRoot "System32"),
        $systemRoot,
        (Join-Path $systemRoot "System32\Wbem"),
        (Join-Path $env:ProgramFiles "PowerShell\7")
    ) -join ";"
    $startInfo.Environment["PATH"] = $restrictedPath
    $startInfo.Environment.Remove("VIRTUAL_ENV")
    $startInfo.Environment.Remove("UV_PROJECT_ENVIRONMENT")

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) {
        throw "clean Windows executable failed to start"
    }
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit(120000)) {
        try {
            $process.Kill($true)
            $null = $process.WaitForExit(5000)
        }
        catch { }
        throw "clean Windows executable command timed out"
    }
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    if ($process.ExitCode -ne 0) {
        throw "clean Windows executable command failed"
    }
    [pscustomobject]@{ Stdout = $stdout; Stderr = $stderr }
}

$artifactPath = (Resolve-Path -LiteralPath $Artifact -ErrorAction Stop).Path
$checksumPath = (Resolve-Path -LiteralPath $Checksum -ErrorAction Stop).Path
$runnerTemp = [IO.Path]::GetFullPath($env:RUNNER_TEMP)
$sessionRoot = Join-Path $runnerTemp ("fbw-clean-" + [guid]::NewGuid().ToString("N"))
$summaryPath = [IO.Path]::GetFullPath($Summary)

New-Item -ItemType Directory -Path $sessionRoot -ErrorAction Stop | Out-Null
try {
    $isolatedArtifact = Join-Path $sessionRoot "fbw-harness.exe"
    Copy-Item -LiteralPath $artifactPath -Destination $isolatedArtifact

    $expectedHash = ((Get-Content -LiteralPath $checksumPath -Raw).Trim() -split "\s+")[0]
    $actualHash = (Get-FileHash -LiteralPath $isolatedArtifact -Algorithm SHA256).Hash
    if ($actualHash -ne $expectedHash) {
        throw "clean Windows SHA-256 verification failed"
    }

    $null = Invoke-IsolatedExe $isolatedArtifact @("--help") $sessionRoot
    $null = Invoke-IsolatedExe $isolatedArtifact @("demo", "all") $sessionRoot
    $firstStatus = Invoke-IsolatedExe $isolatedArtifact @("credential", "status") $sessionRoot
    $secondStatus = Invoke-IsolatedExe $isolatedArtifact @("credential", "status") $sessionRoot
    if ($firstStatus.Stdout -notmatch "configured=False" -or $secondStatus.Stdout -notmatch "configured=False") {
        throw "clean Windows credential state was not empty"
    }

    @(
        "result=PASS",
        "runtime_path=windows-system-only",
        "sha256=PASS",
        "help=PASS",
        "demo_all=PASS",
        "credential_status=PASS",
        "credential_configured=False"
    ) | Set-Content -LiteralPath $summaryPath -Encoding utf8NoBOM
}
finally {
    if (Test-Path -LiteralPath $sessionRoot) {
        Remove-Item -LiteralPath $sessionRoot -Recurse -Force
    }
}
