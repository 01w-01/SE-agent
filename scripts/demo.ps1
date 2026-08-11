$ErrorActionPreference = 'Stop'

$demoRoot = Split-Path -Parent $PSScriptRoot
foreach ($name in 'guardrail', 'feedback', 'no-progress') {
    uv run --project (Join-Path $demoRoot 'mini-harness') fbw-harness demo $name
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
