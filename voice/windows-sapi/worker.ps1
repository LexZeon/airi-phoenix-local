# SPDX-License-Identifier: MIT
# Persistent, text-only SAPI5 worker. Audio is routed only to memory.
param([Parameter(Mandatory=$true)][string]$OwnerLaunchId)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::InputEncoding = New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
function Send-WorkerJson($Value) { [Console]::Out.WriteLine(($Value | ConvertTo-Json -Compress -Depth 5)); [Console]::Out.Flush() }
function Release-Com($Value) { if ($null -ne $Value -and [Runtime.InteropServices.Marshal]::IsComObject($Value)) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($Value) } }
function Get-CommandHash([string]$Value) {
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value)))).Replace('-','').ToLowerInvariant() }
    finally { $hash.Dispose() }
}
$speaker = $null; $selected = $null; $memory = $null
try {
    if ($OwnerLaunchId -notmatch '^[a-f0-9]{32}$') { throw 'Invalid worker owner.' }
    $speaker = New-Object -ComObject SAPI.SpVoice
    $voices = $speaker.GetVoices()
    for ($index=0; $index -lt $voices.Count; $index++) {
        $candidate = $voices.Item($index)
        if ($candidate.Id -match 'TTS_MS_ZH-CN_HUIHUI_11\.0$') { $selected = $candidate; break }
        Release-Com $candidate
    }
    Release-Com $voices
    if (-not $selected) { Send-WorkerJson @{ok=$false;code='VOICE_UNAVAILABLE'}; exit 2 }
    $speaker.Voice = $selected
    $speaker.Volume = 100
    $speaker.AllowAudioOutputFormatChangesOnNextSet = $false
    $self = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $PID)
    Send-WorkerJson @{ok=$true;event='ready';voice='huihui';sample_rate=24000;channels=1;bits=16;identity=@{
        pid=[int]$PID;parentPid=[int]$self.ParentProcessId;executable=[string]$self.ExecutablePath;
        creationTimeUtcTicks=([DateTime]$self.CreationDate).ToUniversalTime().Ticks.ToString([Globalization.CultureInfo]::InvariantCulture);
        commandLineSha256=(Get-CommandHash ([string]$self.CommandLine));launchId=$OwnerLaunchId}}
    while ($null -ne ($line = [Console]::In.ReadLine())) {
        $requestId = ''
        try {
            $request = $line | ConvertFrom-Json
            $requestId = [string]$request.request_id
            if ($requestId -notmatch '^[a-f0-9]{32}$' -or $request.input -isnot [string] -or $request.input.Length -lt 1 -or $request.input.Length -gt 2000 -or $request.rate -isnot [ValueType] -or [int]$request.rate -lt -10 -or [int]$request.rate -gt 10) { throw 'Invalid worker request.' }
            $timer = [Diagnostics.Stopwatch]::StartNew()
            $speaker.Rate = [int]$request.rate
            $memory = New-Object -ComObject SAPI.SpMemoryStream
            $memory.Format.Type = 26 # SAFT24kHz16BitMono
            $speaker.AudioOutputStream = $memory
            [void]$speaker.Speak([string]$request.input, 16) # SVSFIsNotXML: literal text, never filename/SSML.
            [byte[]]$pcm = $memory.GetData()
            # SpMemoryStream contains the stream payload. Construct an explicit PCM RIFF header.
            if ($pcm.Length -lt 2 -or $pcm.Length % 2 -ne 0 -or $pcm.Length -gt 16777216) { throw 'Invalid PCM output.' }
            $waveStream = New-Object IO.MemoryStream
            $writer = New-Object IO.BinaryWriter($waveStream)
            try {
                $writer.Write([Text.Encoding]::ASCII.GetBytes('RIFF')); $writer.Write([uint32](36+$pcm.Length))
                $writer.Write([Text.Encoding]::ASCII.GetBytes('WAVEfmt ')); $writer.Write([uint32]16)
                $writer.Write([uint16]1); $writer.Write([uint16]1); $writer.Write([uint32]24000)
                $writer.Write([uint32]48000); $writer.Write([uint16]2); $writer.Write([uint16]16)
                $writer.Write([Text.Encoding]::ASCII.GetBytes('data')); $writer.Write([uint32]$pcm.Length); $writer.Write($pcm)
                $writer.Flush(); $encoded = [Convert]::ToBase64String($waveStream.ToArray())
            } finally { $writer.Dispose(); $waveStream.Dispose() }
            $timer.Stop()
            Send-WorkerJson @{ok=$true;request_id=$requestId;wav_base64=$encoded;generation_seconds=$timer.Elapsed.TotalSeconds}
        } catch { Send-WorkerJson @{ok=$false;request_id=$requestId;code='SYNTHESIS_FAILED'} }
        finally {
            if ($memory) { Release-Com $memory; $memory = $null }
            $line = $null; $request = $null; $pcm = $null; $encoded = $null
        }
    }
} catch { Send-WorkerJson @{ok=$false;code='WORKER_START_FAILED'}; exit 2 }
finally { Release-Com $memory; Release-Com $selected; Release-Com $speaker }
