# SPDX-License-Identifier: MIT
# Synthetic file-only SAPI comparison. No sound-card playback or default changes.
param(
    [Parameter(Mandatory = $true)][string]$Out,
    [string]$Styles = ''
)
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($Styles)) { $Styles = Join-Path $PSScriptRoot 'styles.json' }
$output = [IO.Path]::GetFullPath($Out)
$repoRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
if ($output -eq $repoRoot -or $output.StartsWith($repoRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Write private benchmark output outside the public repository.' }
if (Test-Path -LiteralPath (Join-Path $output 'report.json')) { throw 'Use a fresh output directory; existing results are preserved.' }
[void](New-Item -ItemType Directory -Path $output -Force)
$config = Get-Content -LiteralPath $Styles -Raw -Encoding UTF8 | ConvertFrom-Json
$text = [string]$config.voices.'phoenix-soft'.sample_text
if ([string]::IsNullOrWhiteSpace($text)) { throw 'The fixed synthetic soft sample text is unavailable.' }

function Get-WaveMetadata([string]$File) {
    $reader = New-Object IO.BinaryReader([IO.File]::OpenRead($File))
    try {
        if ([Text.Encoding]::ASCII.GetString($reader.ReadBytes(4)) -ne 'RIFF') { throw 'Invalid WAV RIFF header.' }
        [void]$reader.ReadUInt32()
        if ([Text.Encoding]::ASCII.GetString($reader.ReadBytes(4)) -ne 'WAVE') { throw 'Invalid WAV format.' }
        $sampleRate = 0; $byteRate = 0; $channels = 0; $bits = 0; $dataBytes = 0
        while ($reader.BaseStream.Position + 8 -le $reader.BaseStream.Length) {
            $tag = [Text.Encoding]::ASCII.GetString($reader.ReadBytes(4))
            $size = $reader.ReadUInt32(); $start = $reader.BaseStream.Position
            if ($start + $size -gt $reader.BaseStream.Length) { throw 'Invalid WAV chunk size.' }
            if ($tag -eq 'fmt ') {
                [void]$reader.ReadUInt16(); $channels = $reader.ReadUInt16()
                $sampleRate = $reader.ReadUInt32(); $byteRate = $reader.ReadUInt32()
                [void]$reader.ReadUInt16(); $bits = $reader.ReadUInt16()
            }
            if ($tag -eq 'data') { $dataBytes += $size }
            $reader.BaseStream.Position = $start + $size + ($size % 2)
        }
        if ($byteRate -le 0 -or $dataBytes -le 0) { throw 'The WAV has no valid audio data.' }
        return @{ sample_rate = $sampleRate; channels = $channels; bits = $bits; audio_seconds = [double]$dataBytes / $byteRate }
    } finally { $reader.Dispose() }
}

$voice = $null; $stream = $null; $selected = $null
$setup = [Diagnostics.Stopwatch]::StartNew()
try {
    $voice = New-Object -ComObject SAPI.SpVoice
    $tokens = $voice.GetVoices()
    for ($index = 0; $index -lt $tokens.Count; $index++) {
        $token = $tokens.Item($index)
        if ($token.Id -match 'TTS_MS_ZH-CN_HUIHUI_11\.0$') { $selected = $token; break }
    }
    if (-not $selected) { throw 'Installed SAPI5 Microsoft Huihui Desktop was not found; no alternative voice was substituted.' }
    $voice.Voice = $selected
    $voice.Rate = 0; $voice.Volume = 100
    $voice.AllowAudioOutputFormatChangesOnNextSet = $false
    $setup.Stop()
    $runs = @()
    for ($round = 1; $round -le 2; $round++) {
        $file = Join-Path $output ('huihui-' + $round + '.wav')
        if (Test-Path -LiteralPath $file) { throw 'An existing sample was preserved; choose a fresh directory.' }
        $timer = [Diagnostics.Stopwatch]::StartNew()
        $stream = New-Object -ComObject SAPI.SpFileStream
        $stream.Format.Type = 26 # SAFT24kHz16BitMono, Microsoft SAPI enum.
        $stream.Open($file, 3, $false) # SSFMCreateForWrite; no playback.
        $voice.AudioOutputStream = $stream
        [void]$voice.Speak($text, 0)
        $stream.Close()
        $timer.Stop()
        $voice.AudioOutputStream = $null
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($stream)
        $stream = $null
        $wave = Get-WaveMetadata $file
        $runs += @{ number = $round; wall_seconds = $timer.Elapsed.TotalSeconds;
            first_complete_wav_seconds = $timer.Elapsed.TotalSeconds; audio_seconds = $wave.audio_seconds;
            rtf = $timer.Elapsed.TotalSeconds / $wave.audio_seconds; sample_rate = $wave.sample_rate;
            channels = $wave.channels; bits = $wave.bits; bytes = (Get-Item -LiteralPath $file).Length;
            audio_sha256 = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant();
            sample_file = [IO.Path]::GetFileName($file) }
    }
    $report = @{ ok = $true; synthetic_only = $true; text = $text; engine = 'Windows SAPI5';
        voice = 'Microsoft Huihui Desktop'; token = 'TTS_MS_ZH-CN_HUIHUI_11.0'; setup_seconds = $setup.Elapsed.TotalSeconds;
        rate = 0; volume = 100; audio_played = $false; network_used = $false; live_service_changed = $false;
        serena_voice_preserved = $false; natural_language_style_instructions_supported = $false; runs = $runs;
        scope = 'A separate system voice option; it does not retain Serena or the Qwen style instructions. No default was changed.' }
    $report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $output 'report.json') -Encoding UTF8
    $report | ConvertTo-Json -Depth 6
} finally {
    if ($stream) { try { $stream.Close() } catch {}; [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($stream) }
    if ($voice) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($voice) }
}
