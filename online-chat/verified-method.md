# Optional ChatGPT-account text chat for AIRI

The adapter exposes a loopback OpenAI-compatible text endpoint, while the official installed Codex CLI handles the existing ChatGPT login and online inference. It never extracts an OpenAI token, reads a browser cookie, or reuses ChatGPT desktop conversation history. AIRI's default remains local 9B; this is a separately selected online option.

## Verified prerequisites and deployment

- Deployed files live at `<base>/runtime/airi-codex-chat`; `<base>/control-center/codex_bridge.py` supplies executable discovery and clean subprocess-environment helpers.
- The verified CLI is `0.164.0-alpha.11.1` and the verified online model is `gpt-6.1-sol`. Official app-server `model/list` returned this account's available default, and actual inference succeeded. A bundled model catalog alone was not used as entitlement proof.
- The chat worker rejects an unverified CLI version or model before inference. Executable path/size/mtime changes trigger version revalidation. Retest a new CLI/model before extending these allowlists. The task assistant has separate permissions and continues to inherit the user's normal model/config.
- The adapter uses port 9948, alias `chatgpt-codex-text`, and a private local bearer secret in `api-token.txt`. This is an adapter secret, not an OpenAI credential. Never publish it, `server-state.json`, logs, worker settings, scratch contents or private console preferences.
- Selecting **ChatGPT 账号 · 在线聊天** and applying/starting AIRI starts this optional service. Switching back to local 9B stops the owned optional adapter. The console also offers **改回离线 9B 并应用**, preserving the other selections shown in the page.

## Chat and task permissions are separate

Every chat request uses a fresh ephemeral/read-only CLI session in a dedicated verified-empty directory, ignores user configuration, disables project instruction loading, and disables 23 tool-related features. Its environment keeps only OS/login/proxy discovery and optional `CODEX_HOME`; it does not inherit the enclosing app's tools pipe, thread/session identity, or permission-profile overrides. No task workspace, existing Codex thread or related writable root is used for chat.

The current CLI can still advertise function names. This implementation does **not** claim that all tool schemas disappear. Instead, Code Mode execution is disabled and must emit the verified fail-closed startup marker. A deliberate harmless execution probe produced the native router diagnostic `code-mode host is disabled`, proving an actual dispatch rejection rather than relying on the model saying it has no tools. The worker withholds output when a tool item, router rejection, unknown protocol event, malformed JSON or unverified permission warning appears. It scans diagnostic lines for rejection without retaining them unboundedly and checks the child has exited before delivering an answer.

The independent Codex task entry is intended for user-submitted tasks. It defaults to read-only and may explicitly grant workspace-write access. Only when the selected directory equals the privately configured AIRI entry project and the user chooses write mode may the configured related AIRI installation root be passed through `--add-dir`; the UI displays that extra scope. Other directories and read-only mode get no such extra authorization. Neither path uses approval-bypass switches or edits global Codex configuration.

## AIRI integration and history

The real `llm` Pinia store publicly returns `models` and `stream`; its compatibility Maps are private. `online-chat-bootstrap.js` uses the public `$onAction` hook on `stream`. Only the exact alias and 9948 Chat Completions endpoint receive `supportsTools:false`, `taskTools:[]`, and `tools:[]`. This prevents new tools from being offered or resolved, including the ordinary artwork tools. Offline 9B and other providers remain unchanged.

Previously completed historical function calls can still appear in AIRI's conversation after tools are disabled. The gateway only projects complete, explicitly paired historical calls/results into labelled ordinary assistant text. It discards arguments. Historical image parts become `[历史图片未发送]` without reading files, fetching URLs or forwarding image bytes. Unmatched/incomplete calls, unknown schemas, new tool definitions and manual image attachments are rejected. This is text-history compatibility, not tool execution or image support. It does not promise that every arbitrary pre-existing conversation format is supported.

## Streaming and measured results

CLI output arrives as completed agent-message events. The adapter waits for the verified completed answer and sends one real content event; it never subdivides a finished reply to imitate token streaming. An early SSE role event is not first visible text.

One real synthetic persona test supplied a short Chinese fictional-character system message and an ordinary greeting, with no user conversation or screen data. The response was a brief, gentle Chinese welcome and did not identify as a coding assistant. First SSE role arrived at 0.0156 seconds; first actual content and completion at 5.953 seconds, one content event. This is one connection-dependent observation, not a latency guarantee or a comparison with AIRI's long real history.

After replacing the invalid private-Map approach with the public action hook, the parent task's real AIRI SDK scene text test passed: the expected synthetic phrase was observed once in assistant output and once at completion in 6.461 seconds. Concurrent gateway counters increased by one completed request with no failure. Counters alone are not treated as causal proof, and scene text completion is not a native speech/microphone test.

## Validation and limits

- Worker: six offline test groups cover permission markers, unknown/malformed events, tool rejection beyond a bounded diagnostic buffer, empty-directory validation, cancellation, final-message delivery, and closed arguments/environment.
- HTTP: thirteen offline tests cover authentication/Host/Origin, large text input, actual SSE event timing, cancellation, bounded concurrency, safe errors, complete historical tool projection, and image/new-tool rejection.
- AIRI bootstrap: seven synthetic tests use the actual public store shape without compatibility Maps and check precise endpoint/model selection and offline preservation.
- Lifecycle: four PowerShell syntax checks and seven mock identity cases pass. Real start, duplicate start, health and stop also pass; duplicate start reused PID/instance, the service was stopped afterwards, and other listening-service PIDs plus AIRI settings hash were unchanged. No cloud inference occurred in the lifecycle test.
- The independent task assistant also passed an actual read-only synthetic-file test: file contents were absent from the prompt, a real command completed with exit 0, the answer matched the file exactly, and the file hash stayed unchanged. The successful diagnostic retry took 15.649 seconds. This is not a task-speed benchmark, old-thread continuation test or real workspace-write validation.
- Ephemeral means no saved session rollout for new independent tasks. It does not claim that the external CLI writes no operational metadata, authentication refresh state or logs. Existing-thread continuation intentionally retains that thread's history. The console itself keeps bounded task results in memory and does not persist task bodies/results.

Actual native end-to-end voice, arbitrary historical chat formats, other cloud models and future Codex versions remain separate validation scopes. The online adapter does not make screen observation active and does not promise faster speech; existing local ASR/TTS selections are retained.

## Primary sources

- https://learn.chatgpt.com/docs/non-interactive-mode
- https://learn.chatgpt.com/docs/cli/reference
- https://learn.chatgpt.com/docs/app-server
- https://learn.chatgpt.com/docs/config-file/config-reference

Publish source, sanitized evidence and these conditions. Keep account data, local bearer secrets, task diagnostics, user folders, screenshots and model assets private.
