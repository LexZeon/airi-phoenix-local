[CmdletBinding()]
param([switch]$NoPause)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'airi-model-common.ps1')
$mutex = New-Object Threading.Mutex($false, 'Local\AICompanionsAiriVisionModel')
$locked = $false
$startedProcess = $null
$launchId = [guid]::NewGuid().ToString('N')
$logs = Join-Path $script:AiriModelBase 'logs'
try {
    $locked = $mutex.WaitOne(200000)
    if (-not $locked) { throw 'Another AIRI model start/stop is still in progress.' }
    New-Item -ItemType Directory -Path $script:AiriModelRuntime, $logs -Force | Out-Null
    $state = Read-AiriModelState
    $existing = Get-AiriModelProcess $state
    if (-not $existing) {
        if (Get-NetTCPConnection -LocalPort $script:AiriModelPort -State Listen -ErrorAction SilentlyContinue) {
            throw 'Port 9941 is occupied by an untracked process. No process was stopped.'
        }
        foreach ($file in @($script:AiriModelExe, $script:AiriModelPath, $script:AiriModelProjector)) {
            if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw ('A local AIRI model file is missing: ' + $file + '. No download was attempted.') }
        }
        if ((Get-Item -LiteralPath $script:AiriModelPath).Length -ne 5680522464 -or (Get-Item -LiteralPath $script:AiriModelProjector).Length -ne 918166080) {
            throw 'The local model/projector size differs from the verified installation.'
        }
        $llamaDirectory = Split-Path -Parent $script:AiriModelExe
        $cudaBin = if ($env:AIRI_CUDA_BIN) { $env:AIRI_CUDA_BIN } else { Join-Path $env:LOCALAPPDATA 'Programs\CUDA\v13.4\bin' }
        $env:PATH = $llamaDirectory + ';' + $cudaBin + ';' + $env:PATH
        $env:HF_HUB_OFFLINE = '1'
        $env:TRANSFORMERS_OFFLINE = '1'
        $env:LLAMA_ARG_OFFLINE = '1'
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $stdout = Join-Path $logs ('airi-model-' + $stamp + '.out.log')
        $stderr = Join-Path $logs ('airi-model-' + $stamp + '.err.log')
        $arguments = @('--host', '127.0.0.1', '--port', '9941', '-m', ('"' + $script:AiriModelPath + '"'),
            '--mmproj', ('"' + $script:AiriModelProjector + '"'), '--alias', $script:AiriModelId,
            '--ctx-size', '32768', '--parallel', '1', '-ngl', '999', '-fa', 'on',
            '--image-min-tokens', '1024', '--image-max-tokens', '2048', '--reasoning', 'off', '--offline', '--no-webui')
        $startedProcess = Start-Process -FilePath $script:AiriModelExe -ArgumentList $arguments -WorkingDirectory $llamaDirectory -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
        $record = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $startedProcess.Id)
        if (-not $record) { throw ('The AIRI model process exited. See ' + $stderr) }
        $state = [pscustomobject]@{
            owner = 'AI-Companions-AIRI-Vision'; launchId = $launchId; pid = $startedProcess.Id
            creationDateUtc = ([datetime]$record.CreationDate).ToUniversalTime().ToString('o')
            executable = $script:AiriModelExe; model = $script:AiriModelPath; projector = $script:AiriModelProjector
            port = $script:AiriModelPort; modelId = $script:AiriModelId; url = $script:AiriModelUrl
            context = 32768; offline = $true; stdout = $stdout; stderr = $stderr; ready = $false
        }
        Write-AiriModelState $state
    }
    $deadline = (Get-Date).AddSeconds(180)
    do {
        if (Test-AiriModelHealth) {
            $state.ready = $true
            Write-AiriModelState $state
            Write-Host ('AIRI local vision model ready: ' + $script:AiriModelUrl + '/v1 ; model=' + $script:AiriModelId)
            exit 0
        }
        $current = Get-AiriModelProcess $state
        if (-not $current) { throw ('AIRI model exited during startup. See ' + $state.stderr) }
        Start-Sleep -Milliseconds 700
    } while ((Get-Date) -lt $deadline)
    throw ('AIRI model did not become ready within 180 seconds. See ' + $state.stderr)
}
catch {
    $message = $_.Exception.Message
    if ($startedProcess) {
        try {
            $state = Read-AiriModelState
            if ($state -and $state.launchId -eq $launchId) {
                $own = Get-AiriModelProcess $state
                if ($own) { Stop-Process -Id ([int]$own.ProcessId) -Force }
                Remove-AiriModelState $launchId
            }
        }
        catch { Write-Warning ('Could not clean up this failed launch: ' + $_.Exception.Message) }
    }
    $message | Out-File -LiteralPath (Join-Path $logs 'airi-model-launch-errors.log') -Append -Encoding UTF8
    if (-not $NoPause) {
        try {
            Add-Type -AssemblyName System.Windows.Forms
            [System.Windows.Forms.MessageBox]::Show(($message + [Environment]::NewLine + 'Logs: ' + $logs), 'AIRI local model', 'OK', 'Error') | Out-Null
        } catch { }
    }
    Write-Error $message -ErrorAction Continue
    exit 1
}
finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
