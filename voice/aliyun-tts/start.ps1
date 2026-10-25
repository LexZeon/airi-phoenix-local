# SPDX-License-Identifier: MIT
param()
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$mutex=New-Object Threading.Mutex($false,'Local\AIRI-Aliyun-TTS-9949');$locked=$false
try{
    try{$locked=$mutex.WaitOne(15000)}catch [Threading.AbandonedMutexException]{$locked=$true}
    if(-not $locked){throw 'Another Aliyun TTS start/stop is active.'}
    $spec=Get-AliyunTtsSpec
    if(-not (Test-Path -LiteralPath $spec.Worker -PathType Leaf)){throw 'The isolated Aliyun TTS worker is missing.'}
    $state=Read-AliyunTtsState $spec
    $identity=if($state){Assert-AliyunTtsIdentity $state.identity $spec $state.launchId}else{$null}
    $owners=@(Get-AliyunTtsPortOwners)
    if($owners.Count -gt 0 -and (-not $identity -or @($owners|Where-Object{$_ -ne $identity.pid}).Count -gt 0)){throw 'Port 9949 belongs to an unverified process; nothing was changed.'}
    if(-not $identity){
        [void](New-Item -ItemType Directory -Path $spec.Logs -Force)
        $launchId=[Guid]::NewGuid().ToString('N');$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
        $arguments=@('-u',('"{0}"' -f $spec.Server),'--host','127.0.0.1','--port','9949','--launch-id',$launchId)
        $child=Start-Process -FilePath $spec.Python -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $spec.Logs ($stamp+'.stdout.log')) -RedirectStandardError (Join-Path $spec.Logs ($stamp+'.stderr.log')) -PassThru
        $deadline=(Get-Date).AddSeconds(20)
        while((Get-Date)-lt $deadline){
            $owners=@(Get-AliyunTtsPortOwners)
            if($owners.Count -eq 1){
                $candidate=Get-AliyunTtsIdentity ([int]$owners[0]) $spec $launchId
                if(-not $candidate -or $candidate.pid -ne $child.Id){throw 'Port listener is not the process just launched; it was left untouched.'}
                $identity=$candidate;break
            }
            if($owners.Count -gt 1){throw 'Multiple port owners; nothing was stopped.'}
            $child.Refresh();if($child.HasExited){throw 'Aliyun TTS exited before binding its port; check its private logs.'}
            Start-Sleep -Milliseconds 200
        }
        if(-not $identity){throw 'Aliyun TTS did not bind its port within 20 seconds.'}
        $state=@{owner='airi-aliyun-tts-9949';schemaVersion=1;port=9949;launchId=$launchId;server=$spec.Server;identity=$identity}
        Write-AliyunTtsState $spec $state
    }
    $checked=Assert-AliyunTtsIdentity $state.identity $spec $state.launchId
    $health=Get-AliyunTtsHealth
    if(-not $checked -or -not $health -or $health.service -ne 'airi-aliyun-tts' -or $health.instance_id -cne $state.launchId -or [int]$health.pid -ne $checked.pid -or -not $health.ready){throw 'The verified Aliyun TTS HTTP adapter is not ready.'}
    Write-Output 'Optional Aliyun cloud TTS adapter ready at http://127.0.0.1:9949. Cloud inference is online; AIRI model selection was not changed.'
    exit 0
}catch{Write-Error $_.Exception.Message -ErrorAction Continue;exit 1}
finally{if($locked){$mutex.ReleaseMutex()};$mutex.Dispose()}
