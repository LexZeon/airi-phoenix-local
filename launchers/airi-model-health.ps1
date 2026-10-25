$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'airi-model-common.ps1')
try {
    $state = Read-AiriModelState
    $record = Get-AiriModelProcess $state
    $healthy = $null -ne $record -and (Test-AiriModelHealth)
    [pscustomobject]@{ ready = $healthy; url = $script:AiriModelUrl; apiBase = ($script:AiriModelUrl + '/v1'); model = $script:AiriModelId; pid = $state.pid; offline = $state.offline; context = $state.context } | ConvertTo-Json
    if (-not $healthy) { exit 1 }
    exit 0
}
catch {
    [pscustomobject]@{ ready = $false; url = $script:AiriModelUrl; error = $_.Exception.Message } | ConvertTo-Json
    exit 1
}
