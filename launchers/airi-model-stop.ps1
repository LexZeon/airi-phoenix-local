[CmdletBinding()]
param([switch]$NoPause)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'airi-model-common.ps1')
$mutex = New-Object Threading.Mutex($false, 'Local\AICompanionsAiriVisionModel')
$locked = $false
try {
    $locked = $mutex.WaitOne(200000)
    if (-not $locked) { throw 'Another AIRI model start/stop is still in progress.' }
    $state = Read-AiriModelState
    if (-not $state) {
        if (Get-NetTCPConnection -LocalPort $script:AiriModelPort -State Listen -ErrorAction SilentlyContinue) { throw 'Port 9941 has no matching AIRI state. It was left untouched.' }
        Write-Host 'AIRI local model is not running.'
        exit 0
    }
    $record = Get-AiriModelProcess $state
    if ($record) {
        Stop-Process -Id ([int]$record.ProcessId) -Force -ErrorAction Stop
        $deadline = (Get-Date).AddSeconds(12)
        do {
            $remaining = Get-CimInstance Win32_Process -Filter ('ProcessId=' + [int]$record.ProcessId)
            if (-not $remaining -or $remaining.CreationDate -ne $record.CreationDate) { break }
            Start-Sleep -Milliseconds 200
        } while ((Get-Date) -lt $deadline)
        if ($remaining -and $remaining.CreationDate -eq $record.CreationDate) { throw 'The AIRI model process has not exited yet.' }
    }
    Remove-AiriModelState ([string]$state.launchId)
    Write-Host 'AIRI local vision model stopped. Unrelated services were left running.'
    exit 0
}
catch {
    $message = $_.Exception.Message
    $message | Out-File -LiteralPath (Join-Path $script:AiriModelBase 'logs\airi-model-stop-errors.log') -Append -Encoding UTF8
    if (-not $NoPause) {
        try {
            Add-Type -AssemblyName System.Windows.Forms
            [System.Windows.Forms.MessageBox]::Show($message, 'AIRI local model stop failed', 'OK', 'Error') | Out-Null
        } catch { }
    }
    Write-Error $message -ErrorAction Continue
    exit 1
}
finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
