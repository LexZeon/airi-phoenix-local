[CmdletBinding()]
param([switch]$NoPause)
$ErrorActionPreference = 'Stop'
$controlPackage = Split-Path -Parent $PSScriptRoot
$controlBase = if ($env:AIRI_COMPANIONS_ROOT) { [IO.Path]::GetFullPath($env:AIRI_COMPANIONS_ROOT) } else { $controlPackage }
$controlRoot = Join-Path $controlPackage 'control-center'
$controlData = if ($env:AIRI_CONTROL_DATA_DIR) { [IO.Path]::GetFullPath($env:AIRI_CONTROL_DATA_DIR) } else { Join-Path $controlRoot 'state' }
$controlPort = if ($env:AIRI_CONTROL_PORT) { [int]$env:AIRI_CONTROL_PORT } else { 9944 }
$controlUrl = 'http://127.0.0.1:' + $controlPort
$controlStatePath = Join-Path $controlData 'server.json'
$controlScript = Join-Path $controlRoot 'server.py'
try {
    if (-not (Test-Path -LiteralPath $controlStatePath)) { Write-Output 'Control center has no recorded server.'; exit 0 }
    $controlState = Get-Content -LiteralPath $controlStatePath -Encoding UTF8 -Raw | ConvertFrom-Json
    if ($controlState.app -ne 'airi-local-control-center' -or $controlState.script -ne $controlScript) { throw 'Control-center ownership record does not match.' }
    $controlProcess = Get-CimInstance Win32_Process -Filter ('ProcessId=' + [int]$controlState.pid) -ErrorAction SilentlyContinue
    if (-not $controlProcess) { Write-Output 'Control center is already stopped.'; exit 0 }
    if (-not $controlProcess.CommandLine -or -not $controlProcess.CommandLine.Contains($controlScript) -or [IO.Path]::GetFileName($controlProcess.ExecutablePath) -ne 'python.exe') { throw 'Recorded process ownership could not be verified. No process was stopped.' }
    $controlHealth = Invoke-RestMethod -Uri ($controlUrl + '/health') -TimeoutSec 3
    if ($controlHealth.app -ne $controlState.app -or [int]$controlHealth.pid -ne [int]$controlState.pid) { throw 'The listening service does not match the owned server.' }
    $controlBoot = Invoke-RestMethod -Uri ($controlUrl + '/api/bootstrap') -TimeoutSec 5
    Invoke-RestMethod -Method Post -Uri ($controlUrl + '/api/shutdown') -Headers @{'Origin'=$controlUrl;'X-Control-CSRF'=$controlBoot.csrfToken} -ContentType 'application/json' -Body '{}' -TimeoutSec 5 | Out-Null
    Write-Output 'Only the AIRI configuration console was stopped. AIRI and model services were left running.'
} catch {
    $_ | Out-String | Add-Content -LiteralPath (Join-Path $controlData 'logs\launcher-error.log')
    if (-not $NoPause) {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show(('Could not stop the owned control center.' + [Environment]::NewLine + $_.Exception.Message), 'Local AI control center') | Out-Null
    }
    throw
}
