# SPDX-License-Identifier: MIT
param()
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
try{
    $spec=Get-AliyunTtsSpec;$state=Read-AliyunTtsState $spec
    if(-not $state){@{service='airi-aliyun-tts';running=$false;ready=$false;verified=$false}|ConvertTo-Json -Compress;exit 1}
    $identity=Assert-AliyunTtsIdentity $state.identity $spec $state.launchId
    $health=Get-AliyunTtsHealth
    $verified=[bool]($identity -and $health -and $health.service -eq 'airi-aliyun-tts' -and $health.instance_id -ceq $state.launchId -and [int]$health.pid -eq $identity.pid)
    @{service='airi-aliyun-tts';running=[bool]$identity;ready=[bool]($verified -and $health.ready);verified=$verified;online=$true;configured=[bool]$health.configured;delivery='complete-wav';firstAudioMetric='upstream-sse'}|ConvertTo-Json -Compress
    if(-not $verified -or -not $health.ready){exit 1}
    exit 0
}catch{@{service='airi-aliyun-tts';ready=$false;verified=$false;error='IDENTITY_OR_HEALTH_FAILED'}|ConvertTo-Json -Compress;exit 1}
