# Official Codex CLI task assistant

This is a user-clicked online task entry in the local AIRI control console. It uses the installed official CLI and its existing login, rather than automating the ChatGPT desktop chat UI. It does not replace AIRI's selected local consciousness model or forward AIRI conversations, screen captures, or settings.

## Implementation

- `codex_bridge.py` discovers `codex.exe` from the path or the desktop installation. `AIRI_CODEX_EXE` can specify the installed executable; `AIRI_CODEX_WORKSPACE` can specify the default workspace. No authentication file, cookie, or token is read/exported by the bridge. Installation/login status comes from `--version` and `login status` and is reduced to whitelisted metadata.
- New independent tasks use `codex exec --json --ephemeral --sandbox read-only --skip-git-repo-check --color never -C <directory> -`. Explicit write mode changes only the sandbox to `workspace-write`.
- An explicitly configured existing-chat target uses `codex exec ... resume <thread-id> -`. This intentionally retains the existing chat's task history. The target ID/default workspace are private local preferences in `state/codex-preferences.json`, excluded from publication.
- Prompts go through stdin. Arguments are a list with `shell=False`; task text never becomes shell command text or a process-list argument. No model is specified, so the user's configured default is inherited. No approval-bypass switches or global config edits are used.
- Working directories must be existing specific local folders. Network/device paths, drive roots, missing folders, unsupported modes, empty/oversized tasks are rejected. A private `relatedWriteRoots` list applies only when the user explicitly selects workspace-write at the configured default entry project; the UI displays the extra scope. Read-only mode and other selected directories do not receive these extra roots.
- One task runs at a time. Task text is not stored in the control-console job records; event/result buffers and job count are bounded in memory. Raw CLI stderr, reasoning items, command bodies and environment/config diagnostics are not exposed by the UI. Error categories are reduced to actionable login, network, usage-limit or permission messages.
- JSON events provide progress and completed agent messages. This is event-level progress, not a claim of token-by-token streaming.
- Stop affects only the tracked child CLI process tree. Closing the console cancels its active Codex task; it does not stop AIRI/model services.
- `/api/codex/status`, `/api/codex/jobs/<id>`, `/api/codex/start`, `/api/codex/stop` use the existing loopback/Host/Origin policy. Writes also require the existing CSRF token. The browser code never submits a task until the user submits its form.

## Observed validation

One actual installed-CLI connectivity check completed using an independent synthetic prompt that requested no tools and exactly `OK`. With CLI `0.164.0-alpha.11.1`, read-only/ephemeral flags and the inherited model default, it returned exactly OK in 3.662 seconds, exit 0, with no tool events or failed turn. This is one network-dependent observation, not a latency guarantee or an AIRI conversation benchmark. No real user content, account details or raw stderr was retained.

Official app-server `initialize` plus metadata-only `thread/read(includeTurns=false)` successfully recognized the user-specified existing local thread and its workspace. Zero turns were requested/returned, and no task was sent to it. The local CLI accepted the parent `--sandbox`/`-C` options before `resume --help`. Actual continuation of this existing desktop thread remains untested until the user explicitly submits a task; the interface must not claim an already verified append.

`python verify_codex_bridge.py` passes 9 offline tests with a fake CLI subprocess and a temporary loopback HTTP server. These cover argument construction, default read-only and explicit write modes, conditional related writable roots, stdin literals, existing/new target arguments, bounded retention, sanitized errors/status, stop/single-job behavior, directory rejection, and Host/Origin/CSRF protection. The fake CLI never contacts OpenAI. These tests do not claim to validate the installed CLI's sandbox enforcement for arbitrary file operations.

A real independent ephemeral/read-only task also read a synthetic file whose contents were not in the prompt, returned the file contents exactly, and left its hash unchanged. A real command-execution completion reported exit 0 and contained the synthetic value. The successful diagnostic retry took 15.649 seconds. This proves a useful local-read task path after environment isolation, not a general speed guarantee, existing-chat append, or real workspace-write test. Only sanitized booleans/timing/tool status are public; private diagnostic output is excluded.

Child CLI processes use a clean OS/login/proxy environment while retaining normal user configuration for tasks. Parent desktop tool pipes, thread/session IDs and permission-profile overrides are not inherited. Ephemeral avoids saving new session rollouts; it does not mean the external CLI writes no operational metadata, auth-refresh state or logs. Continuing an existing thread intentionally retains its history.

Python compilation and JavaScript syntax checks pass. Production page rendering and its real task-button flow are verified separately by the parent task; this report does not claim an existing-thread append was executed.

## Primary sources

- https://learn.chatgpt.com/docs/non-interactive-mode
- https://learn.chatgpt.com/docs/cli/reference
- https://learn.chatgpt.com/docs/app-server#read-a-stored-thread-without-resuming

Publish source, sanitized test summaries and these verified methods. Do not publish private preferences, task text/results, Codex auth/session files, or user workspace contents.
