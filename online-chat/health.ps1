# SPDX-License-Identifier: MIT
param()
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
try{
    $spec=Get-CodexChatSpec;$state=Read-CodexChatState $spec
    if(-not $state){@{service='airi-codex-chat';running=$false;ready=$false;verified=$false}|ConvertTo-Json -Compress;exit 1}
    $identity=Assert-CodexChatIdentity $state.identity $spec $state.launchId
    $health=Get-CodexChatHealth
    $verified=[bool]($identity -and $health -and $health.service -eq 'airi-codex-chat' -and $health.instance_id -ceq $state.launchId -and [int]$health.pid -eq $identity.pid)
    @{service='airi-codex-chat';running=[bool]$identity;ready=[bool]($verified -and $health.ready);verified=$verified;online=$true;streaming='completed-agent-message-events';token_streaming=$false}|ConvertTo-Json -Compress
    if(-not $verified -or -not $health.ready){exit 1}
    exit 0
}catch{@{service='airi-codex-chat';ready=$false;verified=$false;error='IDENTITY_OR_HEALTH_FAILED'}|ConvertTo-Json -Compress;exit 1}
