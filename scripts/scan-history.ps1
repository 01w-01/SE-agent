$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

try {
    $commits = & git rev-list --all 2>$null
    $revListExitCode = $LASTEXITCODE
    if ($revListExitCode -ne 0) {
        throw "git rev-list failed"
    }

    $found = $false
    foreach ($commit in $commits) {
        $matches = & git grep -I -l -E 'sk-[A-Za-z0-9]{12,}' $commit -- . 2>$null
        $gitExitCode = $LASTEXITCODE
        switch ($gitExitCode) {
            0 {
                $found = $true
                foreach ($path in $matches) {
                    Write-Output "$commit $path"
                }
            }
            1 { }
            default { throw "git grep failed" }
        }
    }

    if ($found) {
        exit 1
    }
    exit 0
}
catch {
    [Console]::Error.WriteLine("secret scan failed")
    exit 2
}
