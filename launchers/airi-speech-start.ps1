param()
$ErrorActionPreference = 'Stop'
$speechBase = if ($env:AIRI_COMPANIONS_ROOT) { $env:AIRI_COMPANIONS_ROOT } else { Split-Path -Parent $PSScriptRoot }
$speechRoot = Join-Path $speechBase 'runtime\airi-speech'
$speechConfig = Get-Content -LiteralPath (Join-Path $speechRoot 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$speechPython = $speechConfig.runtime_python
$speechServer = Join-Path $speechRoot 'speech-server.py'
$speechStatePath = Join-Path $speechRoot 'state.json'
$speechUrl = 'http://127.0.0.1:9942'
$speechMutex = New-Object Threading.Mutex($false, 'Local\AICompanions-AIRISpeech')
$speechLocked = $false
function Test-AIRISpeechReady {
    try {
        $speechHealth = Invoke-RestMethod -Uri ($speechUrl + '/health') -TimeoutSec 2
        return ($speechHealth.service -eq 'airi-offline-speech' -and $speechHealth.ready)
    } catch { return $false }
}
try {
    $speechLocked = $speechMutex.WaitOne(0)
    if (-not $speechLocked) { throw 'The local speech service is starting or stopping. Try again shortly.' }
    if (Test-AIRISpeechReady) { Write-Output 'AIRI offline speech is already running on 127.0.0.1:9942.'; exit 0 }
    if (Get-NetTCPConnection -LocalPort 9942 -State Listen -ErrorAction SilentlyContinue) { throw 'Port 9942 is occupied by a different service.' }
    if (-not (Test-Path -LiteralPath $speechPython)) { throw 'The configured shared ARM64 Python interpreter is missing.' }
    $speechLogRoot = Join-Path $speechRoot 'logs'
    New-Item -ItemType Directory -Path $speechLogRoot -Force | Out-Null
    $speechStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $speechOut = Join-Path $speechLogRoot ($speechStamp + '.out.log')
    $speechErr = Join-Path $speechLogRoot ($speechStamp + '.err.log')
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $speechProcess = Start-Process -FilePath $speechPython -ArgumentList @('-u', ('"' + $speechServer + '"')) -WorkingDirectory $speechRoot -WindowStyle Hidden -RedirectStandardOutput $speechOut -RedirectStandardError $speechErr -PassThru
    $speechState = @{ pid = $speechProcess.Id; executable = $speechPython; script = $speechServer; started = (Get-Date).ToString('o'); url = $speechUrl; stdout = $speechOut; stderr = $speechErr }
    $speechState | ConvertTo-Json | Set-Content -LiteralPath $speechStatePath -Encoding UTF8
    $speechDeadline = (Get-Date).AddSeconds(120)
    do {
        if (Test-AIRISpeechReady) {
            $speechListener = Get-NetTCPConnection -LocalPort 9942 -State Listen | Select-Object -First 1
            $speechState.listenerPid = $speechListener.OwningProcess
            $speechState | ConvertTo-Json | Set-Content -LiteralPath $speechStatePath -Encoding UTF8
            Write-Output 'AIRI offline speech is ready on 127.0.0.1:9942.'
            exit 0
        }
        if ($speechProcess.HasExited) { throw "The speech service exited. Read $speechErr" }
        Start-Sleep -Milliseconds 600
    } while ((Get-Date) -lt $speechDeadline)
    throw "The speech service did not start within 120 seconds. Read $speechErr"
} catch {
    Write-Host ('AIRI speech startup failed: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    if ($speechLocked) { $speechMutex.ReleaseMutex() }
    $speechMutex.Dispose()
}
