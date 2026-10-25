$ErrorActionPreference = 'Stop'
$script:AiriBase = if ($env:AIRI_COMPANIONS_ROOT) { $env:AIRI_COMPANIONS_ROOT } else { Split-Path -Parent $PSScriptRoot }
$script:AiriRepo = if ($env:AIRI_REPO_ROOT) { $env:AIRI_REPO_ROOT } else { Join-Path $script:AiriBase 'airi' }

function Get-AiriFileSha256([string]$LiteralPath) {
    $hasher = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($LiteralPath)
    try { return [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-', '') }
    finally { $stream.Dispose(); $hasher.Dispose() }
}
function Install-AiriOfflineShell {
    $template = Join-Path $script:AiriBase 'runtime\airi-offline'
    $destination = Join-Path $script:AiriRepo 'apps\stage-tamagotchi\out\offline-shell'
    if (-not (Test-Path -LiteralPath (Join-Path $template 'main.cjs'))) { throw 'The local AIRI offline integration is missing.' }
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    Get-ChildItem -LiteralPath $template -File | Copy-Item -Destination $destination -Force
    # Transformers 3.x loads this matching ORT pair from a CDN by default.
    # Reuse its installed files so the offline shell can serve the exact pair locally.
    $transformersDist = Join-Path $script:AiriRepo 'apps\stage-tamagotchi\node_modules\@huggingface\transformers\dist'
    $rendererAssets = Join-Path $script:AiriRepo 'apps\stage-tamagotchi\out\renderer\assets'
    & $script:AiriNode (Join-Path $template 'patch-mmd-camera.cjs') --assets $rendererAssets --apply | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'The MMD camera compatibility patch failed. Check the installed AIRI renderer version.' }
    foreach ($assetName in @('ort-wasm-simd-threaded.jsep.mjs', 'ort-wasm-simd-threaded.jsep.wasm')) {
        $assetSource = Join-Path $transformersDist $assetName
        $assetTarget = Join-Path $rendererAssets $assetName
        if (-not (Test-Path -LiteralPath $assetSource)) { throw ('The installed offline audio runtime is missing: ' + $assetName) }
        if (-not (Test-Path -LiteralPath $assetTarget) -or (Get-AiriFileSha256 $assetSource) -ne (Get-AiriFileSha256 $assetTarget)) {
            Copy-Item -LiteralPath $assetSource -Destination $assetTarget -Force
        }
    }
    $packagePath = Join-Path $destination 'package.json'
    $package = Get-Content -LiteralPath $packagePath -Raw | ConvertFrom-Json
    $sourcePackage = Get-Content -LiteralPath (Join-Path $script:AiriRepo 'package.json') -Raw | ConvertFrom-Json
    $package.version = $sourcePackage.version
    $json = $package | ConvertTo-Json -Depth 6
    [IO.File]::WriteAllText($packagePath, $json, (New-Object Text.UTF8Encoding($false)))
    return $destination
}

function Restore-AiriGeneratedMetadata {
    # The upstream VS Code prepare script rewrites this file with LF line endings.
    # Restore checkout line endings only when its normalized content still equals HEAD.
    $generatedPath = 'integrations/vscode/vscode-airi/package.json'
    $currentBlob = & git -C $script:AiriRepo hash-object -- $generatedPath
    $headBlob = & git -C $script:AiriRepo rev-parse ('HEAD:' + $generatedPath)
    if ($LASTEXITCODE -eq 0 -and $currentBlob -eq $headBlob) {
        & git -C $script:AiriRepo restore --source=HEAD --worktree -- $generatedPath
        if ($LASTEXITCODE -ne 0) { throw 'Cannot normalize generated AIRI metadata.' }
    }
}

function Set-AiriEnvironment {
    param([switch]$InstallRuntime)
    $toolVersions = Get-Content -LiteralPath (Join-Path $script:AiriRepo '.tool-versions') -Raw
    if ($toolVersions -notmatch '(?m)^nodejs\s+(\d+\.\d+\.\d+)') { throw 'Cannot read the required Node version.' }
    $nodeVersion = $Matches[1]
    $package = Get-Content -LiteralPath (Join-Path $script:AiriRepo 'package.json') -Raw | ConvertFrom-Json
    if ($package.packageManager -notmatch '^pnpm@(\d+\.\d+\.\d+)') { throw 'Cannot read the required pnpm version.' }
    $pnpmVersion = $Matches[1]
    # AIRI's electron-click-drag-plugin ships a Windows x64 binary only.
    # Keep Node and Electron on x64 so Windows ARM can run the complete desktop app.
    $arch = 'x64'
    $nodeFolder = Join-Path $script:AiriBase "runtime\node-v$nodeVersion-win-$arch"
    $script:AiriNode = Join-Path $nodeFolder 'node.exe'
    if (-not (Test-Path -LiteralPath $script:AiriNode)) {
        if (-not $InstallRuntime) { throw 'The Node runtime is missing. Run the update shortcut.' }
        $archiveName = "node-v$nodeVersion-win-$arch.zip"
        $archive = Join-Path $script:AiriBase "runtime\$archiveName"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri "https://nodejs.org/dist/v$nodeVersion/$archiveName" -OutFile $archive
        $sums = (Invoke-WebRequest -UseBasicParsing -Uri "https://nodejs.org/dist/v$nodeVersion/SHASUMS256.txt").Content
        $hash = (Get-AiriFileSha256 $archive).ToLowerInvariant()
        if ($sums -notmatch ([regex]::Escape($hash) + '\s+' + [regex]::Escape($archiveName))) { throw 'Node checksum verification failed.' }
        Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $script:AiriBase 'runtime') -Force
    }
    $env:PATH = "$nodeFolder;" + $env:PATH
    $pnpmFolder = Join-Path $script:AiriBase "runtime\pnpm-$pnpmVersion"
    $script:AiriPnpm = Join-Path $pnpmFolder 'node_modules\.bin\pnpm.cmd'
    $existingPnpm = Join-Path $script:AiriBase 'runtime\pnpm\node_modules\.bin\pnpm.cmd'
    if (-not (Test-Path -LiteralPath $script:AiriPnpm) -and (Test-Path -LiteralPath $existingPnpm)) {
        $installedVersion = (& $existingPnpm --version | Out-String).Trim()
        if ($installedVersion -eq $pnpmVersion) { $script:AiriPnpm = $existingPnpm }
    }
    if (-not (Test-Path -LiteralPath $script:AiriPnpm)) {
        if (-not $InstallRuntime) { throw 'The pnpm runtime is missing. Run the update shortcut.' }
        & (Join-Path $nodeFolder 'npm.cmd') install --prefix $pnpmFolder "pnpm@$pnpmVersion" --ignore-scripts --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw 'pnpm installation failed.' }
    }
    $env:PATH = (Split-Path -Parent $script:AiriPnpm) + ';' + $env:PATH
    $env:APP_USER_DATA_PATH = Join-Path $script:AiriBase 'runtime\airi-data'
    $env:NODE_OPTIONS = '--max-old-space-size=8192'
    $env:DO_NOT_TRACK = '1'
    $env:APP_DEBUG = '0'
    $env:MAIN_APP_DEBUG = '0'
    $env:APP_REMOTE_DEBUG = 'false'
    $env:AIRI_OFFLINE_BASE = $script:AiriBase
    $env:AIRI_OFFLINE_SOURCE = $script:AiriRepo
    $env:HF_HUB_OFFLINE = '1'
    $env:TRANSFORMERS_OFFLINE = '1'
    New-Item -ItemType Directory -Path $env:APP_USER_DATA_PATH -Force | Out-Null
}
