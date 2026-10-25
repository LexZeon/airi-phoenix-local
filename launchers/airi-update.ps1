$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'airi-env.ps1')
$airiMutex = New-Object System.Threading.Mutex($false, 'Local\AICompanionsAiri')
$airiLockHeld = $false
try {
    $airiLockHeld = $airiMutex.WaitOne(0)
    if (-not $airiLockHeld) { throw 'AIRI is starting or another update is in progress.' }
    $running = @(Get-CimInstance Win32_Process -Filter "Name='electron.exe'" -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -like ('*' + $script:AiriRepo + '*')
    })
    if ($running.Count -gt 0) { throw 'Quit AIRI from its tray menu before updating.' }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backup = Join-Path $script:AiriBase "backups\airi-$stamp"
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    $data = Join-Path $script:AiriBase 'runtime\airi-data'
    if (Test-Path -LiteralPath $data) { Copy-Item -LiteralPath $data -Destination (Join-Path $backup 'airi-data') -Recurse }
    Get-ChildItem -LiteralPath $script:AiriRepo -Force -File -Filter '.env*' | Copy-Item -Destination $backup
    $revision = & git -C $script:AiriRepo rev-parse HEAD
    $revision | Set-Content -LiteralPath (Join-Path $backup 'revision.txt') -Encoding ASCII
    Restore-AiriGeneratedMetadata
    & git -C $script:AiriRepo diff --quiet
    if ($LASTEXITCODE -ne 0) { throw 'AIRI has local source changes. The updater preserves them. Review git diff before updating.' }
    & git -C $script:AiriRepo diff --cached --quiet
    if ($LASTEXITCODE -ne 0) { throw 'AIRI has staged source changes. The updater preserves them. Review git diff --cached before updating.' }
    & git -C $script:AiriRepo pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw 'Cannot fast-forward the AIRI repository.' }
    Set-AiriEnvironment -InstallRuntime
    Push-Location $script:AiriRepo
    try {
        $env:CI = 'true'
        & $script:AiriPnpm install --frozen-lockfile
        if ($LASTEXITCODE -ne 0) { throw 'AIRI dependency installation failed.' }
        Restore-AiriGeneratedMetadata
        & $script:AiriPnpm -F '@proj-airi/stage-tamagotchi' exec install-electron
        if ($LASTEXITCODE -ne 0) { throw 'Electron installation failed.' }
        & $script:AiriPnpm -F '@proj-airi/stage-tamagotchi' build
        if ($LASTEXITCODE -ne 0) { throw 'The AIRI desktop build failed.' }
        Install-AiriOfflineShell | Out-Null
    }
    finally { Pop-Location }
    Write-Host "AIRI updated. Backup: $backup"
    exit 0
}
catch {
    Write-Error $_.Exception.Message -ErrorAction Continue
    exit 1
}
finally {
    if ($airiLockHeld) { $airiMutex.ReleaseMutex() }
    $airiMutex.Dispose()
}
