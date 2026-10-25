[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ProfileFile,
    [switch]$StartAiri
)
$ErrorActionPreference = 'Stop'
$selectionPackage = Split-Path -Parent $PSScriptRoot
$selectionBase = if ($env:AIRI_COMPANIONS_ROOT) { [IO.Path]::GetFullPath($env:AIRI_COMPANIONS_ROOT) } else { $selectionPackage }
$selectionRoot = Join-Path $selectionPackage 'control-center'
$selectionData = if ($env:AIRI_CONTROL_DATA_DIR) { [IO.Path]::GetFullPath($env:AIRI_CONTROL_DATA_DIR) } else { Join-Path $selectionRoot 'state' }
$selectionRequests = [IO.Path]::GetFullPath((Join-Path $selectionData 'requests'))
$selectionPath = [IO.Path]::GetFullPath($ProfileFile)
if ([IO.Path]::GetDirectoryName($selectionPath) -ne $selectionRequests -or [IO.Path]::GetFileName($selectionPath) -notmatch '^selection-[a-f0-9]{32}\.json$') { throw 'Only a managed local selection file is accepted.' }
$selectionResolved = (Resolve-Path -LiteralPath $selectionPath).ProviderPath
if ($selectionResolved -ne $selectionPath) { throw 'Selection path resolution changed.' }
$selectionPython = $env:AIRI_PYTHON
if (-not $selectionPython) { throw 'Set AIRI_PYTHON to an existing compatible Python executable.' }
if (-not (Test-Path -LiteralPath $selectionPython -PathType Leaf)) { throw 'The installed Python runtime is missing. No download was attempted.' }
$env:PYTHONDONTWRITEBYTECODE = '1'
$selectionResult = & $selectionPython (Join-Path $selectionRoot 'profiles.py') --apply-file $selectionPath
if ($LASTEXITCODE -ne 0) { throw 'AIRI profile application failed.' }
$selectionApplied = ($selectionResult -join [Environment]::NewLine) | ConvertFrom-Json
if (-not $selectionApplied.ok) { throw 'AIRI profile was not applied.' }
if (-not $StartAiri) { $selectionResult; exit 0 }
$selectionProfile = Get-Content -LiteralPath $selectionPath -Encoding UTF8 -Raw | ConvertFrom-Json
$selectionShell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
function Invoke-SelectionLauncher([string]$File, [string[]]$Arguments) {
    & $selectionShell -NoProfile -ExecutionPolicy Bypass -File $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw ('Existing launcher failed: ' + [IO.Path]::GetFileName($File)) }
}
if ($selectionProfile.selections.chat -eq 'qwen27') {
    $selectionWorkbench = $env:AIRI_WORKBENCH
    if (-not $selectionWorkbench) { throw 'Set AIRI_WORKBENCH to the existing optional workbench directory.' }
    Invoke-SelectionLauncher (Join-Path $selectionWorkbench 'Switch-Llama.ps1') @('-Model','27B','-NoBrowser')
}
if ($selectionProfile.selections.chat -eq 'ollama' -or $selectionProfile.selections.vision -eq 'ollama') {
    $selectionWorkbench = $env:AIRI_WORKBENCH
    if (-not $selectionWorkbench) { throw 'Set AIRI_WORKBENCH to the existing optional workbench directory.' }
    Invoke-SelectionLauncher (Join-Path $selectionWorkbench 'Start-Ollama.ps1') @()
}
if ($selectionProfile.selections.tts -in @('qwen-soft','qwen-efficient','qwen-drowsy','qwen-focused')) {
    Invoke-SelectionLauncher (Join-Path $selectionBase 'runtime\airi-qwen-tts\start.ps1') @()
}
# Existing AIRI start brings up the already installed visual and SenseVoice/Melo services.
# Preserve services while replacing only the owned AIRI application process.
Invoke-SelectionLauncher (Join-Path $selectionBase 'launchers\airi-stop.ps1') @('-KeepServices','-NoPause')
Invoke-SelectionLauncher (Join-Path $selectionBase 'launchers\airi-start.ps1') @('-NoBrowser')
$selectionResult
