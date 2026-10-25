# SPDX-License-Identifier: MIT
param()
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$mutex=New-Object Threading.Mutex($false,'Local\AIRI-Codex-Chat-9948');$locked=$false
try{
    try{$locked=$mutex.WaitOne(15000)}catch [Threading.AbandonedMutexException]{$locked=$true}
    if(-not $locked){throw 'Another Codex chat start/stop is active.'}
    $spec=Get-CodexChatSpec;$state=Read-CodexChatState $spec
    if(-not $state){Write-Output 'No owned Codex chat service state; nothing was stopped.';exit 0}
    $identity=Assert-CodexChatIdentity $state.identity $spec $state.launchId
    $owners=@(Get-CodexChatPortOwners)
    if($owners.Count -gt 0 -and (-not $identity -or @($owners|Where-Object{$_ -ne $identity.pid}).Count -gt 0)){throw 'Port 9948 has an unverified listener; nothing was stopped.'}
    if($identity){
        # Ask the authenticated service to cancel its own active CLI before any fallback process termination.
        if(Test-Path -LiteralPath $spec.Token -PathType Leaf){
            $token=[IO.File]::ReadAllText($spec.Token).Trim()
            if($token -notmatch '^[A-Za-z0-9_-]{32,128}$'){throw 'Invalid adapter token; nothing was stopped.'}
            try{[void](Invoke-RestMethod -Uri 'http://127.0.0.1:9948/internal/shutdown' -Method Post -ContentType 'application/json' -Headers @{Authorization=('Bearer '+$token)} -Body '{}' -TimeoutSec 5)}catch{}
            $token=$null
        }
        $deadline=(Get-Date).AddSeconds(5)
        do{
            Start-Sleep -Milliseconds 150
            $identity=Assert-CodexChatIdentity $state.identity $spec $state.launchId
        }while($identity -and (Get-Date)-lt $deadline)
        if($identity){Stop-CodexChatOwnedProcess $state.identity $spec $state.launchId}
    }
    Write-Output 'Only this verified optional Codex chat adapter was stopped.'
    exit 0
}catch{Write-Error $_.Exception.Message -ErrorAction Continue;exit 1}
finally{if($locked){$mutex.ReleaseMutex()};$mutex.Dispose()}
