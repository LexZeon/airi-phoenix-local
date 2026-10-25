[CmdletBinding()]
param(
    [ValidateSet('Enable', 'Disable', 'Status')][string]$Action = 'Status',
    [string]$Launcher = (Join-Path $PSScriptRoot 'airi-start.ps1'),
    [string]$StartupDirectory = [Environment]::GetFolderPath('Startup'),
    [string]$ShortcutName = 'AIRI Local Companion.lnk'
)
$ErrorActionPreference = 'Stop'
if ([IO.Path]::GetFileName($ShortcutName) -ne $ShortcutName -or -not $ShortcutName.EndsWith('.lnk', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'ShortcutName must be one .lnk file name.'
}
$launcherPath = [IO.Path]::GetFullPath($Launcher)
$startupPath = [IO.Path]::GetFullPath($StartupDirectory)
$shortcutPath = Join-Path $startupPath $ShortcutName
$powerShellPath = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$expectedArguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $launcherPath + '" -NoBrowser'
$shortcutShell = New-Object -ComObject WScript.Shell
$exists = Test-Path -LiteralPath $shortcutPath -PathType Leaf
$owned = $false
if ($exists) {
    $existingShortcut = $shortcutShell.CreateShortcut($shortcutPath)
    $owned = $existingShortcut.TargetPath -eq $powerShellPath -and $existingShortcut.Arguments -eq $expectedArguments
}
if ($Action -ne 'Status' -and $exists -and -not $owned) {
    throw 'The requested shortcut already exists with a different target. Choose another ShortcutName.'
}
if ($Action -eq 'Enable') {
    if (-not (Test-Path -LiteralPath $launcherPath -PathType Leaf)) { throw 'The existing AIRI launcher was not found.' }
    if (-not (Test-Path -LiteralPath $startupPath -PathType Container)) { throw 'The selected Startup directory was not found.' }
    $shortcut = $shortcutShell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $powerShellPath
    $shortcut.Arguments = $expectedArguments
    $shortcut.WorkingDirectory = Split-Path -Parent (Split-Path -Parent $launcherPath)
    $shortcut.Description = 'Start the existing AIRI launcher and its selected local services after Windows sign-in.'
    $shortcut.WindowStyle = 7
    $shortcut.Save()
} elseif ($Action -eq 'Disable' -and $owned) {
    Remove-Item -LiteralPath $shortcutPath
}
$registered = Test-Path -LiteralPath $shortcutPath -PathType Leaf
$approvedState = 'unavailable'
if ($startupPath -eq [Environment]::GetFolderPath('Startup')) {
    $approved = Get-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder' -ErrorAction SilentlyContinue
    $flag = if ($approved) { $approved.PSObject.Properties[$ShortcutName] } else { $null }
    $approvedState = if (-not $flag) { 'no-explicit-override' } elseif ($flag.Value[0] -in @(3, 7)) { 'disabled-by-Windows' } else { 'present-check-Windows-settings' }
}
[pscustomobject]@{
    registered = $registered
    matchesThisLauncher = ($registered -and (($shortcutShell.CreateShortcut($shortcutPath).TargetPath -eq $powerShellPath) -and ($shortcutShell.CreateShortcut($shortcutPath).Arguments -eq $expectedArguments)))
    windowsStartupState = $approvedState
    startsAfter = 'current-user-sign-in'
    launcherExecutedByThisCommand = $false
} | ConvertTo-Json -Compress
