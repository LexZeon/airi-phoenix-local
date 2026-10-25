# SPDX-License-Identifier: MIT
$ErrorActionPreference='Stop'
function Get-AliyunTtsSpec {
    $companionBase=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $creativePython=Join-Path $env:LOCALAPPDATA 'Programs\SparkAI\envs\creative\Scripts\python.exe'
    $companionPython=Join-Path $companionBase 'open-llm-vtuber\.venv\Scripts\python.exe'
    $candidate=if($env:AIRI_ALIYUN_TTS_PYTHON){$env:AIRI_ALIYUN_TTS_PYTHON}
        elseif(Test-Path -LiteralPath $creativePython -PathType Leaf){$creativePython}
        elseif(Test-Path -LiteralPath $companionPython -PathType Leaf){$companionPython}
        else{(Get-Command python.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source}
    if(-not (Test-Path -LiteralPath $candidate -PathType Leaf)){throw 'Python is not installed.'}
    # This adapter uses only the standard library. Launch the real interpreter directly,
    # since a Windows venv redirector otherwise creates a second Python process.
    $actual=(& $candidate -I -c "import sys; print(getattr(sys, '_base_executable', sys.executable))" | Select-Object -Last 1)
    if($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $actual -PathType Leaf)){throw 'Cannot identify the installed Python executable.'}
    return @{
        Python=(Resolve-Path -LiteralPath $actual).Path
        Server=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'server.py')).Path
        Worker=(Join-Path $PSScriptRoot 'engine.py')
        State=(Join-Path $PSScriptRoot 'server-state.json')
        Token=(Join-Path $PSScriptRoot 'api-token.txt')
        Logs=(Join-Path $PSScriptRoot 'logs')
        Port=9949
    }
}
function Get-AliyunTtsCommandHash([string]$Value) {
    $hash=[Security.Cryptography.SHA256]::Create()
    try{return ([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value)))).Replace('-','').ToLowerInvariant()}
    finally{$hash.Dispose()}
}
function Test-AliyunTtsCommandPath([string]$Command,[string]$Path) {
    return $Command -match ('(?i)(?:^|\s)"?'+[regex]::Escape($Path)+'"?(?:\s|$)')
}
function Get-AliyunTtsIdentity([int]$ProcessId,$Spec,[string]$LaunchId) {
    if($LaunchId -notmatch '^[a-f0-9]{32}$'){throw 'Invalid saved Aliyun TTS launch identity.'}
    $record=Get-CimInstance Win32_Process -Filter ('ProcessId='+$ProcessId) -ErrorAction SilentlyContinue
    if(-not $record){return $null}
    $exe=[string]$record.ExecutablePath;$command=[string]$record.CommandLine
    if([string]::IsNullOrWhiteSpace($exe) -or [string]::IsNullOrWhiteSpace($command)){
        for($attempt=0;$attempt -lt 5;$attempt++){
            Start-Sleep -Milliseconds 100
            $record=Get-CimInstance Win32_Process -Filter ('ProcessId='+$ProcessId) -ErrorAction SilentlyContinue
            if(-not $record){return $null}
            $exe=[string]$record.ExecutablePath;$command=[string]$record.CommandLine
            if(-not [string]::IsNullOrWhiteSpace($exe) -and -not [string]::IsNullOrWhiteSpace($command)){break}
        }
    }
    if($exe -ine $Spec.Python -or -not (Test-AliyunTtsCommandPath $command $Spec.Server) -or $command -notmatch '(?i)--host\s+127\.0\.0\.1(?:\s|$)' -or $command -notmatch '(?i)--port\s+9949(?:\s|$)' -or $command -notmatch ('(?i)--launch-id\s+'+[regex]::Escape($LaunchId)+'(?:\s|$)')){throw 'PID is not this exact Aliyun TTS executable/script/port/launch; it was left untouched.'}
    return @{pid=[int]$record.ProcessId;parentPid=[int]$record.ParentProcessId;executable=$exe;
        creationTimeUtcTicks=([DateTime]$record.CreationDate).ToUniversalTime().Ticks.ToString([Globalization.CultureInfo]::InvariantCulture);
        commandLineSha256=(Get-AliyunTtsCommandHash $command)}
}
function Assert-AliyunTtsIdentity($Saved,$Spec,[string]$LaunchId) {
    if(-not $Saved){throw 'Missing Aliyun TTS identity record.'}
    $current=Get-AliyunTtsIdentity ([int]$Saved.pid) $Spec $LaunchId
    if(-not $current){return $null}
    if($current.executable -ine [string]$Saved.executable -or $current.creationTimeUtcTicks -cne [string]$Saved.creationTimeUtcTicks -or $current.commandLineSha256 -cne [string]$Saved.commandLineSha256 -or $current.parentPid -ne [int]$Saved.parentPid){throw 'Aliyun TTS PID was reused or its identity changed; it was left untouched.'}
    return $current
}
function Read-AliyunTtsState($Spec) {
    if(-not (Test-Path -LiteralPath $Spec.State -PathType Leaf)){return $null}
    $state=Get-Content -LiteralPath $Spec.State -Raw -Encoding UTF8 | ConvertFrom-Json
    if($state.owner -ne 'airi-aliyun-tts-9949' -or $state.schemaVersion -ne 1 -or $state.port -ne 9949 -or $state.server -ine $Spec.Server -or $state.launchId -notmatch '^[a-f0-9]{32}$'){throw 'Unrecognized Aliyun TTS state; nothing was changed.'}
    return $state
}
function Write-AliyunTtsState($Spec,$State) {
    $temporary=$Spec.State+'.'+[Guid]::NewGuid().ToString('N')+'.tmp'
    [IO.File]::WriteAllText($temporary,($State|ConvertTo-Json -Depth 6),(New-Object Text.UTF8Encoding($false)))
    if(Test-Path -LiteralPath $Spec.State){[IO.File]::Replace($temporary,$Spec.State,[System.Management.Automation.Language.NullString]::Value)}else{[IO.File]::Move($temporary,$Spec.State)}
}
function Get-AliyunTtsPortOwners {return @(Get-NetTCPConnection -LocalPort 9949 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)}
function Get-AliyunTtsHealth {try{return Invoke-RestMethod -Uri 'http://127.0.0.1:9949/health' -TimeoutSec 2}catch{return $null}}
function Stop-AliyunTtsOwnedProcess($Saved,$Spec,[string]$LaunchId) {
    $current=Assert-AliyunTtsIdentity $Saved $Spec $LaunchId
    if(-not $current){return}
    $held=$null
    try{
        try{$held=[Diagnostics.Process]::GetProcessById([int]$current.pid);[void]$held.Handle}
        catch{if(-not (Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$current.pid) -ErrorAction SilentlyContinue)){return};throw}
        $checked=Assert-AliyunTtsIdentity $Saved $Spec $LaunchId
        if(-not $checked){return}
        try{$held.Kill();[void]$held.WaitForExit(3000)}catch{if(-not $held.HasExited){throw}}
    }finally{if($held){$held.Dispose()}}
}
