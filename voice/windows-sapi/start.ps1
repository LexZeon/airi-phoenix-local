# SPDX-License-Identifier: MIT
param()
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$mutex=New-Object Threading.Mutex($false,'Local\AIRI-Windows-SAPI-9947');$locked=$false
try {
    try { $locked=$mutex.WaitOne(15000) } catch [Threading.AbandonedMutexException] { $locked=$true }
    if (-not $locked) { throw 'Another SAPI start/stop is active.' }
    $spec=Get-SapiSpec;$state=Read-SapiState $spec
    $identity=if($state){Assert-SapiIdentity $state.identity $spec $state.launchId}else{$null}
    $owners=@(Get-SapiPortOwners)
    if ($owners.Count -gt 0 -and (-not $identity -or @($owners|Where-Object{$_ -ne $identity.pid}).Count -gt 0)) { throw 'Port 9947 belongs to an unverified process; nothing was changed.' }
    if (-not $identity) {
        # Do not orphan a surviving worker from an earlier interrupted server.
        if ($state) {
            $staleWorker=Read-SapiWorkerIdentity $spec $state
            if ($staleWorker) { throw 'A verified old SAPI worker is still running; run this adapter stop.ps1 first.' }
        }
        [void](New-Item -ItemType Directory -Path $spec.Logs -Force)
        $launchId=[Guid]::NewGuid().ToString('N');$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
        $arguments=@('-u',('"{0}"' -f $spec.Server),'--host','127.0.0.1','--port','9947','--launch-id',$launchId)
        $child=Start-Process -FilePath $spec.Launcher -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $spec.Logs ($stamp+'.stdout.log')) -RedirectStandardError (Join-Path $spec.Logs ($stamp+'.stderr.log')) -PassThru
        $launchIdentity=Get-SapiIdentity $child.Id $spec $launchId
        $deadline=(Get-Date).AddSeconds(30)
        while((Get-Date)-lt $deadline) {
            $owners=@(Get-SapiPortOwners)
            if($owners.Count -eq 1) {
                $candidate=Get-SapiIdentity ([int]$owners[0]) $spec $launchId
                if(-not $candidate -or ($candidate.pid -ne $child.Id -and $candidate.parentPid -ne $child.Id)) { throw 'Port listener is not the process just launched; it was left untouched.' }
                $identity=$candidate;break
            }
            if($owners.Count -gt 1) { throw 'Multiple port owners; nothing was stopped.' }
            if($child.HasExited) { throw 'SAPI launcher exited before binding its port.' }
            Start-Sleep -Milliseconds 200
        }
        if(-not $identity) { throw 'SAPI did not bind its port within 30 seconds.' }
        $state=@{owner='airi-sapi-9947';schemaVersion=1;port=9947;launchId=$launchId;server=$spec.Server;workerScript=$spec.Worker;identity=$identity;launcherIdentity=$launchIdentity}
        Write-SapiState $spec $state
    }
    $deadline=(Get-Date).AddSeconds(30)
    while((Get-Date)-lt $deadline) {
        $checked=Assert-SapiIdentity $state.identity $spec $state.launchId
        if(-not $checked) { throw 'Verified SAPI server exited.' }
        $owners=@(Get-SapiPortOwners)
        if($owners.Count -ne 1 -or $owners[0] -ne $checked.pid) { throw 'SAPI port ownership changed.' }
        $health=Get-SapiHealth
        if($health) {
            if($health.service -ne 'airi-windows-sapi' -or $health.instance_id -cne $state.launchId -or [int]$health.pid -ne $checked.pid) { throw 'Unexpected health identity on port 9947.' }
            if($health.ready) {
                $worker=Read-SapiWorkerIdentity $spec $state
                if(-not $worker -or [int]$health.worker_pid -ne $worker.pid) { throw 'Worker identity is not verified.' }
                Write-Output 'Verified optional Windows Huihui TTS ready at http://127.0.0.1:9947. Default AIRI voice was not changed.'
                exit 0
            }
            if(-not $health.loading) { throw ('SAPI unavailable: '+$health.error_code) }
        }
        Start-Sleep -Milliseconds 300
    }
    throw 'SAPI did not become ready within 30 seconds.'
} catch { Write-Error $_.Exception.Message -ErrorAction Continue;exit 1 }
finally { if($locked){$mutex.ReleaseMutex()};$mutex.Dispose() }
