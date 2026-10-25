param()
$ErrorActionPreference = 'Stop'
$speechBase = if ($env:AIRI_COMPANIONS_ROOT) { $env:AIRI_COMPANIONS_ROOT } else { Split-Path -Parent $PSScriptRoot }
$speechRoot = Join-Path $speechBase 'runtime\airi-speech'
$speechConfig = Get-Content -LiteralPath (Join-Path $speechRoot 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$speechPython = $speechConfig.runtime_python
$speechServer = Join-Path $speechRoot 'speech-server.py'
$speechStatePath = Join-Path $speechRoot 'state.json'
$speechMutex = New-Object Threading.Mutex($false, 'Local\AICompanions-AIRISpeech')
$speechLocked = $false
try {
    $speechLocked = $speechMutex.WaitOne(0)
    if (-not $speechLocked) { throw 'The speech service is starting. Wait until startup finishes.' }
    if (-not (Test-Path -LiteralPath $speechStatePath)) { Write-Output 'AIRI offline speech has no running state.'; exit 0 }
    $speechState = Get-Content -LiteralPath $speechStatePath -Raw | ConvertFrom-Json
    $speechParent = Get-CimInstance Win32_Process -Filter ('ProcessId=' + [int]$speechState.pid) -ErrorAction SilentlyContinue
    if (-not $speechParent) { Write-Output 'AIRI offline speech is already stopped.'; exit 0 }
    if ($speechParent.ExecutablePath -ne $speechPython -or -not $speechParent.CommandLine.Contains($speechServer)) { throw 'The saved PID no longer belongs to the AIRI speech process. Nothing was stopped.' }
    $speechChildren = Get-CimInstance Win32_Process -Filter ('ParentProcessId=' + [int]$speechParent.ProcessId) -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine.Contains($speechServer) }
    foreach ($speechChild in $speechChildren) { Stop-Process -Id $speechChild.ProcessId -Force -ErrorAction SilentlyContinue }
    Stop-Process -Id $speechParent.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Output 'AIRI offline speech stopped.'
    exit 0
} catch {
    Write-Host ('AIRI speech stop failed: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    if ($speechLocked) { $speechMutex.ReleaseMutex() }
    $speechMutex.Dispose()
}
