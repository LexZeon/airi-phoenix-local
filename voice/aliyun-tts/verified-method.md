# Optional Aliyun cloud speech for AIRI

This is a local, authenticated OpenAI-compatible WAV adapter. The cloud API Key
stays behind the adapter; AIRI stores only an independent loopback token. No new
model weights or third-party Python packages are needed.

## Standard connection

The default is `qwen3-tts-flash` with `Serena`. The official voice list describes
Serena as a gentle female voice; suitability for a character still needs listening.
Other listed choices are Maia and Seren. The Key's region must match the endpoint:

| Region | Official HTTP endpoint |
| --- | --- |
| Beijing | `https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation` |
| Singapore | `https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation` |

The request uses `Authorization: Bearer ...`, `X-DashScope-SSE: enable`, and
`{model,input:{text,voice,language_type:'Chinese'}}`. It deliberately does not send
unsupported instruction, speed or sample-format parameters in standard mode.

The adapter appends Base64 `output.audio.data` chunks in arrival order, requires
`output.finish_reason='stop'`, and wraps the documented signed 16-bit, little-endian,
24 kHz mono PCM as WAV. The final temporary `audio.url` is not downloaded or logged.
One request is limited to 600 characters; AIRI's normal speech segmentation should
keep individual requests short.

## Advanced emotional speech

The optional advanced model is `qwen-audio-3.1-tts-flash`. It needs a real workspace
API Host copied from the Key-creation dialog or workspace-management page. A
literal `default` workspace is not invented. Hosts must be a single workspace
label under `cn-beijing.maas.aliyuncs.com` or `ap-southeast-1.maas.aliyuncs.com` and
must match the selected region. Credentials, paths, query strings, fragments and
nonstandard ports are rejected.

The advanced request uses `/api/v1/services/audio/tts/SpeechSynthesizer`, with
`input.text`, `voice`, `format:'wav'`, `sample_rate:24000`, `rate:1.0`, and
`instruction`. Region-aware voice choices prevent Beijing-only voices appearing
as Singapore choices. Four cross-region voices are available; three additional
gentle Beijing choices are listed in the controller.

The documentation does not establish this newer model's raw PCM bit depth and
channel layout. Advanced mode therefore requests WAV and validates complete RIFF
containers, sample format, frame lengths and consistency before returning audio.
Split pieces of one complete container and multiple complete same-format sentence
containers are supported. Unknown/incomplete containers produce a clear error;
the adapter does not guess a PCM header or emit noise. Actual advanced cloud output
has not been verified without a configured account and explicit test.

## Credentials and state

- Explicit configuration saves the real cloud Key using Windows current-user
  DPAPI in `private/settings.json`. It is never stored in AIRI's provider entry,
  command arguments, catalog, logs or HTTP health output. Public settings expose
  `keyConfigured` and only whitelisted preference/test fields, never a Key/prefix.
- An empty password input preserves a saved Key; explicit `clearKey` clears it.
  No configured credential is read by the offline tests.
- Each saved change invalidates the prior test result. Test results retain only
  status, UTC time and three numerical timing values. Revision matching prevents
  a test of old settings overwriting the status of newer settings.
- Existing Aliyun users get saved voice/style changes on the next request. Saving
  Aliyun settings does not change AIRI's selected speech provider. The stable
  loopback voice ID is `configured`, whose displayed name is the saved voice.
- `api-token.txt`, `private/`, state, logs and generated audio must be excluded
  from publication. The original user/official character assets are unrelated to
  this adapter and must not be copied into it.

## API and lifecycle

`server.py --host 127.0.0.1 --port 9949 --launch-id <32 lowercase hex characters>`
provides `/health`, `/v1/models`, `/v1/audio/voices`, and authenticated
`POST /v1/audio/speech`. The public model alias is `aliyun-qwen-tts` and the speech
voice alias is `configured`. Speech returns complete WAV only. Authenticated
`POST /internal/shutdown` cancels this instance's active requests and stops it.

Health can be `ready:true,configured:false`: the local HTTP process is ready for
configuration, which is not proof of cloud access. Two upstream requests may run
at once; extra requests are rejected rather than growing an unbounded queue.
Host, Origin, CORS, local bearer token, body/text/output size and time limits are
checked. Endpoint construction is fixed by region/mode; redirects are denied.
Upstream raw error bodies, credential-bearing headers and temporary audio URLs
are not returned to clients.

## Timings and verification boundary

The controller's fixed synthetic test sentence is
“先休息一下吧。我在这里，慢慢来就好。” It reports:

- `firstAudioMs`: first non-empty audio chunk received and decoded from the cloud.
- `completeWavMs`: complete validated playable WAV available from the adapter.
- `audioDurationSeconds`: duration calculated from the actual WAV samples.

The current AIRI compatible speech provider awaits a complete ArrayBuffer before
playing its sentence. Upstream streaming does not automatically give AIRI streaming
playback. These timings are not microphone-to-speaker latency, and no cloud speed
claim is made before an account-backed test. The controller should retain the
working local voice until the user chooses to apply the tested online option.

`python verify_adapter.py` currently passes 25 offline checks. They use temporary
fixtures, synthetic current-user DPAPI encryption/decryption, fake HTTP/SSE audio,
actual WAV decoding, safe error handling, endpoint validation, separate first/full
audio timing, authenticated temporary-loopback HTTP and bounded cancellation.
They make zero real cloud requests and read zero real credentials. Mock timing
values are not cloud performance evidence. Actual owned-process lifecycle and
the production controller's rendered interface are separate owner checks.

## Primary documentation

- [Qwen3 TTS HTTP API](https://help.aliyun.com/zh/model-studio/qwen-tts-api)
- [Qwen3 voice list](https://help.aliyun.com/zh/model-studio/qwen-tts-voice-list)
- [Qwen-Audio TTS HTTP API](https://help.aliyun.com/zh/model-studio/qwen-audio-tts-http-api)
- [Qwen-Audio voice list](https://help.aliyun.com/zh/model-studio/qwen-audio-tts-voice-list)
- [Regional domains and migration](https://help.aliyun.com/zh/model-studio/regions)
- [Get an API Key](https://help.aliyun.com/zh/model-studio/get-api-key)

## Separate native owner checks

[Real Windows PowerShell lifecycle](verification-lifecycle-live.json) passed start, duplicate start with the same identity, health and stop. The standard-library adapter resolves a venv redirector to its real base interpreter before launching, so strict listener/executable/PID checks remain valid. Other services and AIRI settings were preserved; the adapter had no Key and made zero cloud calls.

[Actual controller browser acceptance](../../control-center/verification-aliyun-console-production.json) passed the visible no-Key configuration flow and preserved the current local voice and off screen permission. AIRI was stopped and remained stopped. This adds real UI evidence to the offline fixtures; real cloud synthesis, speed, voice quality and native AIRI playback remain unmeasured.
