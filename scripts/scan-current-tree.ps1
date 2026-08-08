$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

try {
    $matches = & git grep -I -l -E 'sk-[A-Za-z0-9]{12,}' -- . 2>$null
    $gitExitCode = $LASTEXITCODE
}
catch {
    [Console]::Error.WriteLine("secret scan failed")
    exit 2
}

switch ($gitExitCode) {
    0 {
        $matches | Write-Output
        exit 1
    }
    1 {
        exit 0
    }
    default {
        [Console]::Error.WriteLine("secret scan failed")
        exit 2
    }
}
