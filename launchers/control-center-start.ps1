[CmdletBinding()]
param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$controlPackage = Split-Path -Parent $PSScriptRoot
$controlBase = if ($env:AIRI_COMPANIONS_ROOT) { [IO.Path]::GetFullPath($env:AIRI_COMPANIONS_ROOT) } else { $controlPackage }
$controlRoot = Join-Path $controlPackage 'control-center'
$controlData = if ($env:AIRI_CONTROL_DATA_DIR) { [IO.Path]::GetFullPath($env:AIRI_CONTROL_DATA_DIR) } else { Join-Path $controlRoot 'state' }
$controlPort = if ($env:AIRI_CONTROL_PORT) { [int]$env:AIRI_CONTROL_PORT } else { 9944 }
$controlUrl = 'http://127.0.0.1:' + $controlPort
$controlServer = Join-Path $controlRoot 'server.py'
$controlLog = Join-Path $controlData 'logs'
$controlMutex = New-Object Threading.Mutex($false, 'Local\AIRICharacterForgeControlCenter')
$controlLocked = $false
function Test-ControlCenterReady {
    try {
        $controlHealth = Invoke-RestMethod -Uri ($controlUrl + '/health') -TimeoutSec 2
        return ($controlHealth.app -eq 'airi-local-control-center' -and $controlHealth.ready)
    } catch { return $false }
}
try {
    $controlLocked = $controlMutex.WaitOne(45000)
    if (-not $controlLocked) { throw 'Another control-center launch is still in progress.' }
    if (-not (Test-ControlCenterReady)) {
        if (Get-NetTCPConnection -LocalPort $controlPort -State Listen -ErrorAction SilentlyContinue) {
            throw 'Port 9944 belongs to another service. No existing service was stopped.'
        }
        $controlPython = $env:AIRI_PYTHON
        if (-not $controlPython -or -not (Test-Path -LiteralPath $controlPython -PathType Leaf)) { throw 'Set AIRI_PYTHON to an existing compatible Python executable. No runtime was downloaded.' }
        New-Item -ItemType Directory -Path $controlLog -Force | Out-Null
        $controlProcess = Start-Process -FilePath $controlPython -ArgumentList @('-u', ('"' + $controlServer + '"')) -WorkingDirectory $controlRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $controlLog 'server.stdout.log') -RedirectStandardError (Join-Path $controlLog 'server.stderr.log') -PassThru
        $controlReady = $false
        for ($controlAttempt = 0; $controlAttempt -lt 50; $controlAttempt++) {
            if (Test-ControlCenterReady) { $controlReady = $true; break }
            if ($controlProcess.HasExited) { break }
            Start-Sleep -Milliseconds 500
        }
        if (-not $controlReady) { throw ('Control center did not become ready. See ' + $controlLog) }
    }
    if (-not $NoBrowser) { Start-Process -FilePath $controlUrl }
    Write-Output ('Personal AIRI console is ready: ' + $controlUrl)
} catch {
    New-Item -ItemType Directory -Path $controlLog -Force | Out-Null
    $_ | Out-String | Add-Content -LiteralPath (Join-Path $controlLog 'launcher-error.log')
    if (-not $NoBrowser) {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show(('Could not open the local AI control center.' + [Environment]::NewLine + $_.Exception.Message + [Environment]::NewLine + $controlLog), 'Local AI control center') | Out-Null
    }
    throw
} finally {
    if ($controlLocked) { $controlMutex.ReleaseMutex() }
    $controlMutex.Dispose()
}
