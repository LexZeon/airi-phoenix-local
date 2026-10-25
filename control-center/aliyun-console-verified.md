# Aliyun speech in the AIRI console

The console exposes an optional **阿里云 · 在线语音** choice under character speech. This is a configured cloud service, not an installed local speech model. The existing local chat/vision/recognition/speech selection is preserved until the user explicitly applies another profile.

## Verified configuration path

1. Selecting the Aliyun option opens its configuration dialog; it does not silently apply the provider. The same dialog is available from the selected speech card.
2. Simple speech requires a region and an API Key. It uses the adapter's supported preset voices. The advanced section exposes the separate expressive model, its official API Host, compatible voice names and style instructions. The dialog does not imply that the simple model supports style instructions.
3. Saving uses `AliyunTtsBridge` and the runtime `aliyun_config.py` module. The cloud key is protected by Windows current-user DPAPI. Empty password input preserves a saved key, and public responses contain only status booleans, not a key or key prefix. The backend and UI do not put the cloud key into the AIRI provider.
4. The user triggers **试听测速** to generate one fixed synthetic Chinese sentence. The test endpoint accepts no arbitrary text or file. The console retains the resulting WAV in memory and serves it only through one fixed sample path. Configuration changes invalidate the sample/test, and a test from an older revision cannot replace the newer settings' result.
5. **使用这个方案** requires the current configuration's successful test. It selects the draft speech choice; the existing Apply and Restart action writes the actual AIRI profile. The `aliyun-tts` profile points to loopback port 9949 using a separate local token and the stable `configured` voice alias. The alias prevents a saved cloud voice name from becoming a stale AIRI voice ID.
6. The speech card offers a system-voice fallback, not the chat model's 9B fallback. Cloud speech and online chat have separate descriptions/actions. Existing profile application continues to preserve card identity and update the three managed cards' speech module selections.

Saving does not change the selected speech provider. When AIRI already uses the Aliyun provider, a deliberate save of its voice/style/key affects its next synthesis; the dialog labels this behavior. It does not add a second candidate/active configuration layer.

## Timing and data boundaries

- `firstAudioMs` means the first upstream audio block arrived. `completeWavMs` means a complete validated playable WAV is available. The UI also shows the audio's duration.
- The current AIRI compatible speech path collects a complete small sentence before playback. An upstream first block is not a measured microphone-to-speaker time or proof of streaming playback in AIRI.
- The cloud voice processes text being synthesized. This feature does not upload microphone audio or desktop captures. The existing default-off screen behavior and local recognition provider remain separate.
- Config, test and sample routes keep the console's loopback Host/Origin policy; writes require the existing CSRF token. No secret appears in a URL. Vendor response bodies are not exposed as user-facing errors.

## Observed checks

`verify_aliyun_console.py` passes 14 isolated checks using a temporary configuration directory, synthetic DPAPI-protected credentials, a fake synthesis engine and a temporary HTTP server. They cover configuration redaction, preserving the local selection, fixed test input, valid WAV/timing responses, clearing failed samples, revision races, single-test locking, malformed audio/timing rejection, missing-key catalog visibility, Host/Origin/CSRF rejection, fixed sample paths, safe cloud failures, stable provider/voice alias behavior and actual `renderModules` output in a Node VM.

The existing nine-case `verify_online_choice.py` profile fixture also passes. Python compilation and the changed browser scripts' syntax checks pass. These tests send no real cloud request, read no real cloud credential, restart no production service, and do not prove the production browser or AIRI audio path. A real API Key and explicit synthetic trial are required before publishing a cloud latency result or recommending a switch.

## Production browser acceptance

[The separate actual browser report](verification-aliyun-console-production.json) confirms the restarted controller displayed the Aliyun entry, opened its dialog without selecting a different voice, and operated region/voice and advanced style controls. With no Key, test/apply remained disabled. Closing the unsaved dialog preserved the system-voice selection, the stopped AIRI process and the off screen setting. No credential was entered and no cloud request was sent. This verifies the rendered no-Key workflow, not cloud audio or native AIRI playback.
