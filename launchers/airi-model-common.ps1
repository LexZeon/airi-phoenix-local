$ErrorActionPreference = 'Stop'
$script:AiriModelBase = if ($env:AIRI_COMPANIONS_ROOT) { $env:AIRI_COMPANIONS_ROOT } else { Split-Path -Parent $PSScriptRoot }
$script:AiriModelRuntime = Join-Path $script:AiriModelBase 'runtime\airi-vision'
$script:AiriModelExe = if ($env:AIRI_LLAMA_SERVER) { $env:AIRI_LLAMA_SERVER } else { Join-Path $env:LOCALAPPDATA 'Programs\llama.cpp\llama-server.exe' }
$script:AiriModelPath = $env:AIRI_GGUF_MODEL
if ([string]::IsNullOrWhiteSpace($script:AiriModelPath)) { throw 'Set AIRI_GGUF_MODEL to your existing Qwen3.5-9B-Q4_K_M.gguf file.' }
$script:AiriModelProjector = if ($env:AIRI_MMPROJ) { $env:AIRI_MMPROJ } else { Join-Path $script:AiriModelRuntime 'mmproj-F16.gguf' }
$script:AiriModelStatePath = Join-Path $script:AiriModelRuntime 'server.json'
$script:AiriModelUrl = 'http://127.0.0.1:9941'
$script:AiriModelId = 'airi-qwen3.5-9b'
$script:AiriModelPort = 9941

function Test-AiriModelPath([string]$First, [string]$Second) {
    return -not [string]::IsNullOrWhiteSpace($First) -and -not [string]::IsNullOrWhiteSpace($Second) -and [string]::Equals([IO.Path]::GetFullPath($First), [IO.Path]::GetFullPath($Second), [StringComparison]::OrdinalIgnoreCase)
}
function Test-AiriModelCommandPath([string]$CommandLine, [string]$Path) {
    return $CommandLine -match ('(^|[\s"])' + [regex]::Escape($Path) + '([\s"]|$)')
}
function Read-AiriModelState {
    if (-not (Test-Path -LiteralPath $script:AiriModelStatePath -PathType Leaf)) { return $null }
    return Get-Content -LiteralPath $script:AiriModelStatePath -Raw | ConvertFrom-Json
}
function Get-AiriModelProcess($State) {
    if (-not $State) { return $null }
    if ($State.owner -ne 'AI-Companions-AIRI-Vision' -or [int]$State.port -ne $script:AiriModelPort -or -not (Test-AiriModelPath $State.model $script:AiriModelPath) -or -not (Test-AiriModelPath $State.projector $script:AiriModelProjector)) {
        throw 'AIRI model state identity does not match this installation.'
    }
    $record = Get-CimInstance Win32_Process -Filter ('ProcessId=' + [int]$State.pid)
    if (-not $record) { return $null }
    $creation = ([datetime]$record.CreationDate).ToUniversalTime().ToString('o')
    if (-not (Test-AiriModelPath $record.ExecutablePath $script:AiriModelExe) -or $creation -ne $State.creationDateUtc -or -not (Test-AiriModelCommandPath $record.CommandLine $script:AiriModelPath) -or -not (Test-AiriModelCommandPath $record.CommandLine $script:AiriModelProjector) -or $record.CommandLine -notmatch '(^|\s)--port\s+9941(\s|$)' -or $record.CommandLine -notmatch '(^|\s)--host\s+127\.0\.0\.1(\s|$)' -or $record.CommandLine -notmatch '(^|\s)--offline(\s|$)') {
        throw ('AIRI model PID ' + $State.pid + ' was reused or has a different identity; it was left untouched.')
    }
    return $record
}
function Test-AiriModelHealth {
    try {
        $health = Invoke-RestMethod -Uri ($script:AiriModelUrl + '/health') -TimeoutSec 3
        if ($health.status -ne 'ok') { return $false }
        $models = Invoke-RestMethod -Uri ($script:AiriModelUrl + '/v1/models') -TimeoutSec 3
        $match = @($models.data | Where-Object { $_.id -eq $script:AiriModelId -and 'image' -in $_.architecture.input_modalities })
        return $match.Count -eq 1
    }
    catch { return $false }
}
function Write-AiriModelState($State) {
    $temporary = Join-Path $script:AiriModelRuntime ('server.' + $State.launchId + '.tmp')
    [IO.File]::WriteAllText($temporary, ($State | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $temporary -Destination $script:AiriModelStatePath -Force
}
function Remove-AiriModelState([string]$LaunchId) {
    $state = Read-AiriModelState
    if ($state -and $state.launchId -eq $LaunchId) { Remove-Item -LiteralPath $script:AiriModelStatePath -Force }
}
