# SPDX-License-Identifier: MIT
$ErrorActionPreference = 'Stop'
function Get-SapiSpec {
    $launcher = if ($env:AIRI_SAPI_PYTHON) { $env:AIRI_SAPI_PYTHON } else { Join-Path $env:LOCALAPPDATA 'Programs\SparkAI\envs\creative\Scripts\python.exe' }
    $venv = Join-Path (Split-Path (Split-Path $launcher -Parent) -Parent) 'pyvenv.cfg'
    $homeLine = Get-Content -LiteralPath $venv -Encoding UTF8 | Where-Object { $_ -match '^home\s*=\s*' } | Select-Object -First 1
    if (-not $homeLine) { throw 'Cannot identify the configured Python executable.' }
    $pythonHome = ($homeLine -replace '^home\s*=\s*','').Trim()
    return @{
        Launcher=(Resolve-Path -LiteralPath $launcher).Path
        BaseExe=(Resolve-Path -LiteralPath (Join-Path $pythonHome 'python.exe')).Path
        Server=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'server.py')).Path
        Worker=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'worker.ps1')).Path
        PowerShell=(Resolve-Path -LiteralPath (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe')).Path
        State=(Join-Path $PSScriptRoot 'state.json');WorkerState=(Join-Path $PSScriptRoot 'worker-state.json')
        Logs=(Join-Path $PSScriptRoot 'logs');Port=9947
    }
}
function Get-SapiCommandHash([string]$Value) {
    $hash=[Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value)))).Replace('-','').ToLowerInvariant() }
    finally { $hash.Dispose() }
}
function Test-SapiCommandPath([string]$Command,[string]$Path) {
    return $Command -match ('(?i)(?:^|\s)"?' + [regex]::Escape($Path) + '"?(?:\s|$)')
}
function Get-SapiIdentity([int]$ProcessId,$Spec,[string]$LaunchId,[string]$Kind='server') {
    if ($LaunchId -notmatch '^[a-f0-9]{32}$') { throw 'Invalid saved SAPI launch identity.' }
    $record=Get-CimInstance Win32_Process -Filter ('ProcessId='+$ProcessId) -ErrorAction SilentlyContinue
    if (-not $record) { return $null }
    $exe=[string]$record.ExecutablePath;$command=[string]$record.CommandLine
    # CIM can briefly enumerate an exiting child with its executable/command
    # already cleared after the parent closes stdin. Never stop such a record;
    # give it a bounded chance to disappear, otherwise fail closed.
    if([string]::IsNullOrWhiteSpace($exe) -or [string]::IsNullOrWhiteSpace($command)) {
        for($attempt=0;$attempt -lt 5;$attempt++) {
            Start-Sleep -Milliseconds 100
            $record=Get-CimInstance Win32_Process -Filter ('ProcessId='+$ProcessId) -ErrorAction SilentlyContinue
            if(-not $record){return $null}
            $exe=[string]$record.ExecutablePath;$command=[string]$record.CommandLine
            if(-not [string]::IsNullOrWhiteSpace($exe) -and -not [string]::IsNullOrWhiteSpace($command)){break}
        }
    }
    if ($Kind -eq 'worker') {
        if ($exe -ine $Spec.PowerShell -or -not (Test-SapiCommandPath $command $Spec.Worker) -or $command -notmatch ('(?i)-OwnerLaunchId\s+'+[regex]::Escape($LaunchId)+'(?:\s|$)')) { throw 'Worker PID is not this exact SAPI worker; it was left untouched.' }
    } else {
        if (($exe -ine $Spec.Launcher -and $exe -ine $Spec.BaseExe) -or -not (Test-SapiCommandPath $command $Spec.Server) -or $command -notmatch '(?i)--host\s+127\.0\.0\.1(?:\s|$)' -or $command -notmatch '(?i)--port\s+9947(?:\s|$)' -or $command -notmatch ('(?i)--launch-id\s+'+[regex]::Escape($LaunchId)+'(?:\s|$)')) { throw 'Server PID is not this exact SAPI executable/script/port/launch; it was left untouched.' }
    }
    return @{pid=[int]$record.ProcessId;parentPid=[int]$record.ParentProcessId;executable=$exe;
        creationTimeUtcTicks=([DateTime]$record.CreationDate).ToUniversalTime().Ticks.ToString([Globalization.CultureInfo]::InvariantCulture);
        commandLineSha256=(Get-SapiCommandHash $command)}
}
function Assert-SapiIdentity($Saved,$Spec,[string]$LaunchId,[string]$Kind='server') {
    if (-not $Saved) { throw 'Missing SAPI identity record.' }
    $current=Get-SapiIdentity ([int]$Saved.pid) $Spec $LaunchId $Kind
    if (-not $current) { return $null }
    if ($current.executable -ine [string]$Saved.executable -or $current.creationTimeUtcTicks -cne [string]$Saved.creationTimeUtcTicks -or $current.commandLineSha256 -cne [string]$Saved.commandLineSha256 -or $current.parentPid -ne [int]$Saved.parentPid) { throw 'SAPI process identity changed or PID was reused; it was left untouched.' }
    return $current
}
function Read-SapiState($Spec) {
    if (-not (Test-Path -LiteralPath $Spec.State -PathType Leaf)) { return $null }
    $state=Get-Content -LiteralPath $Spec.State -Raw | ConvertFrom-Json
    if ($state.owner -ne 'airi-sapi-9947' -or $state.schemaVersion -ne 1 -or $state.port -ne 9947 -or $state.server -ine $Spec.Server -or $state.workerScript -ine $Spec.Worker -or $state.launchId -notmatch '^[a-f0-9]{32}$') { throw 'Unrecognized SAPI state identity; nothing was changed.' }
    return $state
}
function Write-SapiState($Spec,$State) {
    $temporary=$Spec.State+'.'+[Guid]::NewGuid().ToString('N')+'.tmp'
    [IO.File]::WriteAllText($temporary,($State|ConvertTo-Json -Depth 6),(New-Object Text.UTF8Encoding($false)))
    if (Test-Path -LiteralPath $Spec.State) { [IO.File]::Replace($temporary,$Spec.State,[System.Management.Automation.Language.NullString]::Value) } else { [IO.File]::Move($temporary,$Spec.State) }
}
function Get-SapiPortOwners { return @(Get-NetTCPConnection -LocalPort 9947 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique) }
function Get-SapiHealth { try { return Invoke-RestMethod -Uri 'http://127.0.0.1:9947/health' -TimeoutSec 2 } catch { return $null } }
function Read-SapiWorkerIdentity($Spec,$State) {
    if (-not (Test-Path -LiteralPath $Spec.WorkerState -PathType Leaf)) { return $null }
    $saved=Get-Content -LiteralPath $Spec.WorkerState -Raw | ConvertFrom-Json
    if ($saved.owner -ne 'airi-sapi-9947' -or $saved.schemaVersion -ne 1 -or $saved.launchId -cne $State.launchId -or [int]$saved.serverPid -ne [int]$State.identity.pid -or [int]$saved.worker.parentPid -ne [int]$State.identity.pid -or $saved.worker.launchId -cne $State.launchId) { throw 'Worker ownership record does not match this server; it was left untouched.' }
    return Assert-SapiIdentity $saved.worker $Spec $State.launchId 'worker'
}
function Stop-SapiOwnedProcess($Saved,$Spec,[string]$LaunchId,[string]$Kind='server') {
    $current=Assert-SapiIdentity $Saved $Spec $LaunchId $Kind
    if(-not $current){return}
    $held=$null
    try {
        try { $held=[Diagnostics.Process]::GetProcessById([int]$current.pid);[void]$held.Handle }
        catch { if(-not (Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$current.pid) -ErrorAction SilentlyContinue)){return};throw }
        # Hold the native process handle, then verify again. Kill uses that held process,
        # avoiding a reused PID and the harmless race where a child exits with its parent.
        $checked=Assert-SapiIdentity $Saved $Spec $LaunchId $Kind
        if(-not $checked){return}
        try { $held.Kill();[void]$held.WaitForExit(3000) }
        catch { if(-not $held.HasExited){throw} }
    } finally { if($held){$held.Dispose()} }
}
