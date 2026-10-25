# SPDX-License-Identifier: MIT
param()
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$mutex=New-Object Threading.Mutex($false,'Local\AIRI-Windows-SAPI-9947');$locked=$false
try {
    try{$locked=$mutex.WaitOne(15000)} catch [Threading.AbandonedMutexException] {$locked=$true}
    if(-not $locked){throw 'Another SAPI start/stop is active.'}
    $spec=Get-SapiSpec;$state=Read-SapiState $spec
    if(-not $state){Write-Output 'No owned SAPI service state; nothing was stopped.';exit 0}
    $server=Assert-SapiIdentity $state.identity $spec $state.launchId
    # Validate the worker before stopping either process. The server may refresh this record after cancellation.
    $worker=Read-SapiWorkerIdentity $spec $state
    $launcher=if($state.launcherIdentity){Assert-SapiIdentity $state.launcherIdentity $spec $state.launchId}else{$null}
    $owners=@(Get-SapiPortOwners)
    if($owners.Count -gt 0 -and (-not $server -or @($owners|Where-Object{$_ -ne $server.pid}).Count -gt 0)){throw 'Port 9947 has an unverified listener; nothing was stopped.'}
    if($server){Stop-SapiOwnedProcess $state.identity $spec $state.launchId}
    # Read again after the server is stopped to close the narrow worker-restart race.
    $worker=Read-SapiWorkerIdentity $spec $state
    if($worker){Stop-SapiOwnedProcess $worker $spec $state.launchId 'worker'}
    if($launcher -and (!$server -or $launcher.pid -ne $server.pid)){
        Stop-SapiOwnedProcess $state.launcherIdentity $spec $state.launchId
    }
    Write-Output 'Only this verified optional SAPI server and its worker were stopped.'
    exit 0
}catch{Write-Error $_.Exception.Message -ErrorAction Continue;exit 1}
finally{if($locked){$mutex.ReleaseMutex()};$mutex.Dispose()}
