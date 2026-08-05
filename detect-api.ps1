# detect-api.ps1
# PowerShell 7+

$BaseUrl = "https://njusehub.info/v1"
$ApiKey  = "sk-jyJkUrZptO0eGj7pCV0MeWKUC2obasdK0etwvuuZ4eLL1QKn"

$BaseUrl = $BaseUrl.TrimEnd("/")

function Write-ProbeResult {
    param(
        [string]$Name,
        [string]$State,
        [int]$StatusCode,
        [string]$Detail
    )

    $mark = switch ($State) {
        "Supported" { "[OK]" }
        "Exists"    { "[??]" }
        default     { "[--]" }
    }

    Write-Host ""
    Write-Host ("{0} {1}" -f $mark, $Name)
    Write-Host ("     HTTP: {0}" -f $StatusCode)

    if ($Detail) {
        Write-Host ("     {0}" -f $Detail)
    }
}

function Get-HttpErrorDetail {
    param(
        [System.Management.Automation.ErrorRecord]$ErrorRecord
    )

    $statusCode = 0
    $detail = $ErrorRecord.Exception.Message

    if ($null -ne $ErrorRecord.Exception.Response) {
        try {
            $statusCode = [int]$ErrorRecord.Exception.Response.StatusCode
        }
        catch {
            $statusCode = 0
        }
    }

    if ($ErrorRecord.ErrorDetails.Message) {
        $rawError = $ErrorRecord.ErrorDetails.Message

        try {
            $parsed = $rawError | ConvertFrom-Json -ErrorAction Stop

            if ($parsed.error.message) {
                $detail = [string]$parsed.error.message
            }
            elseif ($parsed.message) {
                $detail = [string]$parsed.message
            }
            elseif ($parsed.error) {
                $detail = [string]$parsed.error
            }
            else {
                $detail = $rawError
            }
        }
        catch {
            $detail = $rawError
        }
    }

    return @{
        StatusCode = $statusCode
        Detail     = $detail
    }
}

function Get-AvailableModels {
    param(
        [string]$BaseUrl,
        [string]$ApiKey
    )

    $headers = @{
        Authorization = "Bearer $ApiKey"
    }

    try {
        $response = Invoke-RestMethod `
            -Uri "$BaseUrl/models" `
            -Method Get `
            -Headers $headers `
            -ErrorAction Stop

        if ($null -eq $response.data) {
            throw "响应中没有 data 字段，无法识别模型列表。"
        }

        $models = @(
            $response.data |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_.id) } |
                ForEach-Object { [string]$_.id } |
                Sort-Object -Unique
        )

        if ($models.Count -eq 0) {
            throw "模型列表为空。"
        }

        return $models
    }
    catch {
        $errorInfo = Get-HttpErrorDetail -ErrorRecord $_

        Write-Host ""
        Write-Host "获取模型列表失败。"
        Write-Host "HTTP: $($errorInfo.StatusCode)"
        Write-Host $errorInfo.Detail

        exit 1
    }
}

function Select-Model {
    param(
        [string[]]$Models
    )

    Write-Host ""
    Write-Host "可用模型："
    Write-Host ""

    for ($i = 0; $i -lt $Models.Count; $i++) {
        Write-Host ("[{0,3}] {1}" -f ($i + 1), $Models[$i])
    }

    while ($true) {
        Write-Host ""
        $inputValue = Read-Host "请输入模型序号，或直接输入模型名称"

        if ([string]::IsNullOrWhiteSpace($inputValue)) {
            Write-Host "输入不能为空。"
            continue
        }

        $number = 0

        if ([int]::TryParse($inputValue, [ref]$number)) {
            if ($number -ge 1 -and $number -le $Models.Count) {
                return $Models[$number - 1]
            }

            Write-Host "序号范围应为 1 到 $($Models.Count)。"
            continue
        }

        $exactMatch = $Models |
            Where-Object { $_ -eq $inputValue } |
            Select-Object -First 1

        if ($exactMatch) {
            return $exactMatch
        }

        $partialMatches = @(
            $Models |
                Where-Object {
                    $_.IndexOf(
                        $inputValue,
                        [System.StringComparison]::OrdinalIgnoreCase
                    ) -ge 0
                }
        )

        if ($partialMatches.Count -eq 1) {
            Write-Host "已匹配模型：$($partialMatches[0])"
            return $partialMatches[0]
        }

        if ($partialMatches.Count -gt 1) {
            Write-Host ""
            Write-Host "匹配到多个模型："

            foreach ($match in $partialMatches) {
                Write-Host "  $match"
            }

            continue
        }

        Write-Host "没有找到该模型，请重新输入。"
    }
}

function Invoke-ApiProbe {
    param(
        [string]$Name,
        [string]$Uri,
        [hashtable]$Headers,
        [hashtable]$Body,
        [ValidateSet(
            "OpenAIChat",
            "OpenAIResponses",
            "AnthropicMessages"
        )]
        [string]$ResponseType
    )

    try {
        $response = Invoke-RestMethod `
            -Uri $Uri `
            -Method Post `
            -Headers $Headers `
            -ContentType "application/json" `
            -Body ($Body | ConvertTo-Json -Depth 20 -Compress) `
            -ErrorAction Stop

        $recognized = switch ($ResponseType) {
            "OpenAIChat" {
                $response.object -eq "chat.completion" -or
                $null -ne $response.choices
            }

            "OpenAIResponses" {
                $response.object -eq "response" -or
                $null -ne $response.output
            }

            "AnthropicMessages" {
                $response.type -eq "message" -or
                $null -ne $response.content
            }
        }

        if ($recognized) {
            Write-ProbeResult `
                -Name $Name `
                -State "Supported" `
                -StatusCode 200 `
                -Detail "接口可用，返回结构符合预期。"
        }
        else {
            Write-ProbeResult `
                -Name $Name `
                -State "Exists" `
                -StatusCode 200 `
                -Detail "请求成功，但返回结构无法明确识别。"
        }
    }
    catch {
        $errorInfo = Get-HttpErrorDetail -ErrorRecord $_
        $statusCode = $errorInfo.StatusCode

        $state = if ($statusCode -in 400, 422, 429) {
            "Exists"
        }
        else {
            "Unsupported"
        }

        $explanation = switch ($statusCode) {
            400 { "接口可能存在，但请求参数或模型格式不兼容。" }
            401 { "API Key 无效或未填写。" }
            403 { "当前 API Key 没有该接口或模型的权限。" }
            404 { "接口路径未开放。" }
            405 { "接口存在，但请求方法不被允许。" }
            422 { "接口可能存在，但请求体校验失败。" }
            429 { "接口可能存在，但触发了额度或限流。" }
            500 { "网关或上游服务发生错误。" }
            502 { "网关无法连接上游服务。" }
            503 { "服务暂时不可用。" }
            504 { "上游请求超时。" }
            default { "请求失败。" }
        }

        Write-ProbeResult `
            -Name $Name `
            -State $state `
            -StatusCode $statusCode `
            -Detail "$explanation $($errorInfo.Detail)"
    }
}

Clear-Host

Write-Host "API 协议检测"
Write-Host "Base URL: $BaseUrl"

if ([string]::IsNullOrWhiteSpace($ApiKey)) {
    Write-Host ""
    Write-Host '请编辑脚本顶部的 $ApiKey，然后重新运行。'
    exit 1
}

$models = Get-AvailableModels `
    -BaseUrl $BaseUrl `
    -ApiKey $ApiKey

$selectedModel = Select-Model -Models $models

Write-Host ""
Write-Host "已选择模型：$selectedModel"
Write-Host ""
Write-Host "开始检测接口，测试请求会使用极少量 Token。"

$openAiHeaders = @{
    Authorization = "Bearer $ApiKey"
}

$anthropicHeaders = @{
    "x-api-key"         = $ApiKey
    "anthropic-version" = "2023-06-01"
}

Invoke-ApiProbe `
    -Name "OpenAI Chat Completions (/chat/completions)" `
    -Uri "$BaseUrl/chat/completions" `
    -Headers $openAiHeaders `
    -ResponseType "OpenAIChat" `
    -Body @{
        model      = $selectedModel
        max_tokens = 1
        messages   = @(
            @{
                role    = "user"
                content = "1"
            }
        )
    }

Invoke-ApiProbe `
    -Name "OpenAI Responses (/responses)" `
    -Uri "$BaseUrl/responses" `
    -Headers $openAiHeaders `
    -ResponseType "OpenAIResponses" `
    -Body @{
        model             = $selectedModel
        input             = "1"
        max_output_tokens = 1
    }

Invoke-ApiProbe `
    -Name "Anthropic Messages (/messages)" `
    -Uri "$BaseUrl/messages" `
    -Headers $anthropicHeaders `
    -ResponseType "AnthropicMessages" `
    -Body @{
        model      = $selectedModel
        max_tokens = 1
        messages   = @(
            @{
                role    = "user"
                content = "1"
            }
        )
    }

Write-Host ""
Write-Host "检测完成。"
Write-Host ""
Write-Host "[OK] 接口可用且返回格式符合预期"
Write-Host "[??] 接口可能存在，但参数、额度或上游状态导致请求失败"
Write-Host "[--] 鉴权失败、路径未开放或服务异常"