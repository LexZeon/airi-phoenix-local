param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'airi-env.ps1')
function Test-AiriOfflineReady($Health, $Preset) {
    if ($Health.app -ne 'airi-offline-helper' -or -not $Health.ready -or -not $Health.originalMainLoaded -or -not $Health.profile.applied -or $Health.profile.revision -ne $Preset.revision) { return $false }
    if ($Preset.character.enabled -and $Health.character.phase -ne 'active') { return $false }
    foreach ($character in @($Preset.additionalCharacters)) {
        if ($character.activate -and -not @($Health.additionalCharacters | Where-Object { $_.id -eq $character.id -and $_.phase -eq 'active' -and $_.activated }).Count) { return $false }
    }
    if ($Preset.stickers.enabled -and $Health.stickers.phase -ne 'ready') { return $false }
    if ($Preset.mmdIdle.enabled -and $Health.mmdIdle.phase -ne 'ready') { return $false }
    return $true
}
$airiMutex = New-Object System.Threading.Mutex($false, 'Local\AICompanionsAiri')
$airiLockHeld = $false
try {
    $airiLockHeld = $airiMutex.WaitOne(30000)
    if (-not $airiLockHeld) { throw 'AIRI is starting or updating. Wait for it to finish.' }
    Set-AiriEnvironment
    $shell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    & $shell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'airi-model-start.ps1') -NoPause
    if ($LASTEXITCODE -ne 0) { throw 'The local 9B model did not become ready.' }
    & $shell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'airi-speech-start.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'The offline speech service did not become ready.' }
    try { $offlinePreset = Get-Content -LiteralPath (Join-Path $script:AiriBase 'runtime\airi-offline\offline-settings.json') -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw 'The offline preset is not valid UTF-8 JSON. Check runtime\airi-offline\offline-settings.json.' }
    $chatProviders = @($offlinePreset.modules.consciousness.provider, $offlinePreset.character.modulesOverride.consciousness.provider)
    foreach ($managedCharacter in @($offlinePreset.additionalCharacters)) { $chatProviders += $managedCharacter.modulesOverride.consciousness.provider }
    $needsCodexChat = $false
    foreach ($providerId in @($chatProviders | Where-Object { $_ })) {
        $providerProperty = $offlinePreset.providers.PSObject.Properties[$providerId]
        if ($providerProperty -and $providerProperty.Value.config.baseUrl -match '^http://(?:127\.0\.0\.1|localhost|\[::1\]):9948(?:/|$)') { $needsCodexChat = $true }
    }
    if ($needsCodexChat) {
        & $shell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $script:AiriBase 'runtime\airi-codex-chat\start.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'The selected ChatGPT online chat adapter did not become ready.' }
    } elseif (Test-Path -LiteralPath (Join-Path $script:AiriBase 'runtime\airi-codex-chat\server-state.json')) {
        & $shell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $script:AiriBase 'runtime\airi-codex-chat\stop.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'The optional online chat adapter could not be safely stopped for local mode.' }
    }
    $selectedSpeechProviders = @($offlinePreset.modules.speech.provider)
    if ($offlinePreset.character.modulesOverride.speech.provider) { $selectedSpeechProviders += $offlinePreset.character.modulesOverride.speech.provider }
    foreach ($managedCharacter in @($offlinePreset.additionalCharacters)) {
        if ($managedCharacter.modulesOverride.speech.provider) { $selectedSpeechProviders += $managedCharacter.modulesOverride.speech.provider }
    }
    $needsQwenSpeech = $false
    $needsSapiSpeech = $false
    foreach ($providerId in $selectedSpeechProviders) {
        $providerProperty = $offlinePreset.providers.PSObject.Properties[$providerId]
        if ($providerProperty -and $providerProperty.Value.config.baseUrl -match '^http://(?:127\.0\.0\.1|localhost|\[::1\]):9945(?:/|$)') { $needsQwenSpeech = $true }
        if ($providerProperty -and $providerProperty.Value.config.baseUrl -match '^http://(?:127\.0\.0\.1|localhost|\[::1\]):9947(?:/|$)') { $needsSapiSpeech = $true }
    }
    if ($needsQwenSpeech) {
        & $shell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $script:AiriBase 'runtime\airi-qwen-tts\start.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'The selected Qwen character voice did not become ready. Check runtime\airi-qwen-tts\logs.' }
    }
    if ($needsSapiSpeech) {
        & $shell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $script:AiriBase 'runtime\airi-sapi\start.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'The selected Windows voice adapter did not become ready.' }
    }
    $electron = Join-Path $script:AiriRepo 'apps\stage-tamagotchi\node_modules\electron\dist\electron.exe'
    $appDir = Join-Path $script:AiriRepo 'apps\stage-tamagotchi'
    $main = Join-Path $appDir 'out\main\index.js'
    if (-not (Test-Path -LiteralPath $electron) -or -not (Test-Path -LiteralPath $main)) {
        throw 'The AIRI desktop build is missing. Run the update shortcut and check logs.'
    }
    $launchDir = Install-AiriOfflineShell
    $existing = @(Get-CimInstance Win32_Process -Filter "Name='electron.exe'" -ErrorAction SilentlyContinue | Where-Object {
        $_.ExecutablePath -like ($script:AiriRepo + '\*\electron.exe') -and
        $_.CommandLine.Contains('"' + $launchDir + '"') -and
        $_.CommandLine -notmatch '\s--type='
    })
    if ($existing.Count -gt 0) {
        try { $existingHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:9943/health' -TimeoutSec 5 } catch { throw 'AIRI is running but its offline helper is not healthy. Stop and start AIRI again.' }
        if (-not (Test-AiriOfflineReady $existingHealth $offlinePreset)) { throw 'AIRI is running but its selected offline setup is incomplete. Stop and start AIRI again.' }
        if ($existingHealth.profile.revision -ne $offlinePreset.revision) { throw 'The selected setup has changed. Use Apply and Restart in your AIRI control panel.' }
        $primary = $existing | Sort-Object CreationDate | Select-Object -First 1
        $primary.ProcessId | Set-Content -LiteralPath (Join-Path $script:AiriBase 'runtime\airi.pid') -Encoding ASCII
        # The application also has a single-instance guard.
        Start-Process -FilePath $electron -ArgumentList ('"' + $launchDir + '"') -WorkingDirectory $appDir
        exit 0
    }
    $logOut = Join-Path $script:AiriBase 'logs\airi-start.stdout.log'
    $logErr = Join-Path $script:AiriBase 'logs\airi-start.stderr.log'
    $process = Start-Process -FilePath $electron -ArgumentList ('"' + $launchDir + '"') -WorkingDirectory $appDir -PassThru -RedirectStandardOutput $logOut -RedirectStandardError $logErr
    $process.Id | Set-Content -LiteralPath (Join-Path $script:AiriBase 'runtime\airi.pid') -Encoding ASCII
    Start-Sleep -Seconds 5
    $process.Refresh()
    if ($process.HasExited -and $process.ExitCode -ne 0) { throw "AIRI exited with code $($process.ExitCode). See $logErr" }
    $deadline = (Get-Date).AddSeconds(45)
    $ready = $false
    do {
        try { $health = Invoke-RestMethod -Uri 'http://127.0.0.1:9943/health' -TimeoutSec 2; $ready = Test-AiriOfflineReady $health $offlinePreset } catch { }
        if (-not $ready) { Start-Sleep -Milliseconds 700 }
    } while (-not $ready -and (Get-Date) -lt $deadline -and -not $process.HasExited)
    if (-not $ready) { throw 'The AIRI offline integration did not become ready. Check the launch log.' }
    exit 0
}
catch {
    $message = $_.Exception.Message
    $message | Out-File -LiteralPath (Join-Path $script:AiriBase 'logs\airi-launch-error.log') -Append -Encoding UTF8
    if (-not $NoBrowser) {
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show($message, 'AIRI launch failed') | Out-Null
    }
    Write-Error $message -ErrorAction Continue
    exit 1
}
finally {
    if ($airiLockHeld) { $airiMutex.ReleaseMutex() }
    $airiMutex.Dispose()
}
