param([switch]$KeepServices, [switch]$NoPause)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'airi-env.ps1')
$mutex = New-Object Threading.Mutex($false, 'Local\AICompanionsAiri')
$held = $false
try {
    $held = $mutex.WaitOne(30000)
    if (-not $held) { throw 'AIRI is starting or updating. Wait before stopping it.' }
    $state = Join-Path $script:AiriBase 'runtime\airi.pid'
    if (Test-Path -LiteralPath $state) {
        $mainId = [int](Get-Content -LiteralPath $state -Raw).Trim()
        $main = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $mainId)
        if ($main) {
            $appPath = Join-Path $script:AiriRepo 'apps\stage-tamagotchi'
            if ($main.ExecutablePath -notlike ($script:AiriRepo + '\*\electron.exe') -or $main.CommandLine -notlike ('*' + $appPath + '*')) {
                throw 'The recorded AIRI process does not match this installation.'
            }
            $all = @(Get-CimInstance Win32_Process -Filter "Name='electron.exe'")
            $owned = New-Object System.Collections.Generic.List[object]
            $parents = @($mainId)
            while ($parents.Count -gt 0) {
                $next = @()
                foreach ($candidate in $all) {
                    if ([int]$candidate.ParentProcessId -in $parents -and $candidate.ExecutablePath -eq $main.ExecutablePath -and $candidate.CreationDate -ge $main.CreationDate) {
                        $owned.Add($candidate)
                        $next += [int]$candidate.ProcessId
                    }
                }
                $parents = $next
            }
            $now = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $mainId)
            if ($now -and $now.CreationDate -eq $main.CreationDate -and $now.CommandLine -eq $main.CommandLine) { Stop-Process -Id $mainId }
            Start-Sleep -Seconds 1
            foreach ($candidate in $owned) {
                $now = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $candidate.ProcessId)
                if ($now -and $now.CreationDate -eq $candidate.CreationDate -and $now.ExecutablePath -eq $candidate.ExecutablePath) { Stop-Process -Id $now.ProcessId }
            }
        }
        Remove-Item -LiteralPath $state -Force
    }
    if (-not $KeepServices) {
        $shell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
        foreach ($helper in @('airi-model-stop.ps1', 'airi-speech-stop.ps1')) {
            $path = Join-Path $PSScriptRoot $helper
            if (Test-Path -LiteralPath $path) {
                if ($helper -eq 'airi-model-stop.ps1') { & $shell -NoProfile -ExecutionPolicy Bypass -File $path -NoPause }
                else { & $shell -NoProfile -ExecutionPolicy Bypass -File $path }
                if ($LASTEXITCODE -ne 0) { throw ('AIRI service stop failed: ' + $helper) }
            }
        }
        $qwenStop = Join-Path $script:AiriBase 'runtime\airi-qwen-tts\stop.ps1'
        if (Test-Path -LiteralPath $qwenStop) {
            & $shell -NoProfile -ExecutionPolicy Bypass -File $qwenStop
            if ($LASTEXITCODE -ne 0) { throw 'The Qwen character voice service could not be safely stopped.' }
        }
        $sapiStop = Join-Path $script:AiriBase 'runtime\airi-sapi\stop.ps1'
        if (Test-Path -LiteralPath $sapiStop) {
            & $shell -NoProfile -ExecutionPolicy Bypass -File $sapiStop
            if ($LASTEXITCODE -ne 0) { throw 'The Windows voice adapter could not be safely stopped.' }
        }
    }
    Write-Output 'AIRI stopped.'
    exit 0
}
catch {
    $message = $_.Exception.Message
    if (-not $NoPause) {
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show($message, 'AIRI stop failed') | Out-Null
    }
    Write-Error $message -ErrorAction Continue
    exit 1
}
finally {
    if ($held) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
