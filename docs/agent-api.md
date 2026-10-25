# Agent API: local CLI and optional MCP

The rig tool is a local program that another agent can call without a particular chat product, AI account, API key, or network connection. Use the CLI directly if your agent can run programs. Use the optional MCP stdio adapter if your client supports legacy MCP **2025-11-25**.

The adapter uses Python 3.10+ standard library only. The rig builder's own dependencies must be installed in the same Python environment. Neither interface downloads dependencies, source art, models, or Live2D Core during a tool call. Supply assets locally and retain the appropriate permission to use them.

## Direct CLI

From the extracted tool folder:

```text
python rig-tools/rig.py inspect --project work/character/project.json --json
python rig-tools/rig.py build --project work/character/project.json --out work/character/build-001 --json
python rig-tools/rig.py validate --model work/character/build-001/Character.model3.json --core-file /path/to/your/live2dcubismcore.js --json
```

Use the actual model path returned by `build`; do not assume the example name. CLI stdout is one JSON object with `ok`, `stage`, `code`, `outputs`, and `summary`. A failure remains a failure; inspect its stage and code before retrying. See `python rig-tools/rig.py --help` for current CLI options. The direct CLI does not acquire the MCP adapter's workspace restrictions merely by using `--json`.

## Start MCP stdio

Choose an existing workspace containing only the project files the agent should use. Projects, input images, model references, and outputs must all stay inside it. The tool program itself can be installed elsewhere.

```text
python /path/to/tool/agent_bridge/server.py --workspace /path/to/my-work --core-file /path/to/my-licensed/live2dcubismcore.js
```

`--core-file` is optional for inspect/build. Validation requires it. This flag explicitly authorizes that **one local JavaScript file**, even outside the workspace. Tool arguments cannot substitute another Core file. Core is not bundled, copied, or downloaded. `--timeout 300` controls the maximum seconds per rig subprocess (range 1–3600).

Many MCP clients accept a configuration shaped like this; use the configuration field names required by your client:

```json
{
  "mcpServers": {
    "phoenix-local-rig": {
      "command": "C:/path/to/python.exe",
      "args": [
        "C:/path/to/tool/agent_bridge/server.py",
        "--workspace", "C:/path/to/my-work",
        "--core-file", "C:/path/to/my-licensed/live2dcubismcore.js"
      ]
    }
  }
}
```

Use an explicit Python executable from the environment that has the rig dependencies. No global PATH edits are needed. Do not launch the adapter by hand and then type prose into its stdin: stdin/stdout carry newline-delimited UTF-8 JSON-RPC messages. Operational diagnostics go to stderr.

## Exposed tools

| Tool | Arguments | Files changed | Behavior |
| --- | --- | --- | --- |
| `inspect` | `project` | None | Inspect project JSON and local source images. |
| `build` | `project`, `out` | New files under `out` | Output must be a new or empty workspace directory. Existing files are preserved. |
| `validate` | `model` | None | Validate a local `.model3.json` with the Core file selected at server startup. |

Arguments are strings. Paths may be relative to the workspace or absolute paths inside it. Additional tool arguments are rejected. For example:

```json
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"build","arguments":{"project":"character/project.json","out":"character/build-001"}}}
```

Each successful protocol response contains a tool result with both `structuredContent` (the CLI JSON object) and a text block containing the same serialized JSON. `isError` reflects the result's `ok`. Tool definitions include input/output schemas and annotations: inspect/validate are read-only; build writes files; no tool is marked destructive or open-world. Client software decides how to present or approve tool calls.

Unknown tools or malformed JSON-RPC parameters return protocol errors. Bad paths, missing files, missing Core, a failed build/validation, malformed CLI output, and timeouts return tool results with `isError: true`. Adapter error codes include `OUTSIDE_WORKSPACE`, `PATH_TRAVERSAL`, `OUTPUT_NOT_EMPTY`, `CORE_NOT_CONFIGURED`, `RIG_TIMEOUT`, and `INVALID_RIG_OUTPUT`.

## Protocol scope

This is deliberately a **legacy MCP 2025-11-25** server, not a claim to implement the latest protocol. It supports `initialize`, `notifications/initialized`, `ping`, `tools/list`, and `tools/call`. It advertises only a fixed tools capability. It does not expose a network listener, resources, prompts, sampling, elicitation, background tasks, or client filesystem roots. Requests execute serially; no task/cancellation facility is advertised.

Initialization example:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"my-local-agent","version":"1.0"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
```

An unsupported version in an `initialize` request negotiates the supported `2025-11-25` version; clients that cannot use it should disconnect. The newer 2026-07-28 revision uses per-request metadata and `server/discover`. This adapter returns method-not-found for that probe so clients with the documented legacy fallback can use initialization. A modern-only client needs a legacy-compatible configuration or can use the direct CLI.

Implementation references: [2025-11-25 lifecycle and version negotiation](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle), [stdio transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports), [tools and structured results](https://modelcontextprotocol.io/specification/2025-11-25/server/tools), and [2026-07-28 versioning and legacy compatibility](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning).

## Local file boundary

The adapter canonicalizes paths and checks their resolved locations. It rejects parent traversal, external absolute paths, URLs, Windows device paths/alternate data streams, and symlink/junction paths that leave the workspace. It also checks `project.asset_root`, every source image, and standard `.model3.json` file references. Build output must resolve inside the workspace and be new or empty. The workspace root itself cannot be an output directory. Subprocess arguments are fixed arrays with `shell=False`; filenames cannot become shell commands.

This is an application-level file boundary, not an operating-system sandbox. Select a dedicated workspace; do not concurrently replace its directories or links during a call. The local builder and explicitly supplied Core file are trusted code. The adapter provides no tool for networking, downloads, publication, arbitrary commands, arbitrary external file reads, or deletion.

## Verification

Run the independent protocol and boundary tests from the tool folder:

```text
python -m unittest discover -s agent_bridge/tests -v
```

Tests cover a real stdio process, initialization, listing/calling tools, structured results, errors, fixed argv, input traversal, referenced asset escape, model references, symlink/junction escape, nonempty output preservation, Core selection, and subprocess timeout. Stub tests validate the adapter independently of the builder. The separate recorded real-fixture test verifies the bundled builder; passing protocol tests alone does not establish that a Live2D model is accepted by Core or visually satisfactory in AIRI.

Recorded on 2026-10-25: [18 protocol/boundary tests passed with no skips](../agent_bridge/tests/protocol-test-report.json), and [actual MCP inspect → build → Core validate passed](../agent_bridge/tests/real-fixture-test-report.json) on the bundled robot example. The latter created the recorded model files in a temporary workspace, validated `RobotDemo.model3.json`, and rejected a traversal request. To repeat the actual builder test, run `python agent_bridge/tests/verify_real_fixture.py --project rig-tools/examples/robot/project.json --core-file /path/to/your/Core.js`; optionally supply `--node /path/to/node` if Node is not already on your process PATH.

Adapter code and these tests are MIT licensed; see [agent_bridge/LICENSE](../agent_bridge/LICENSE). Asset and third-party licenses remain separate.

## Other production modes

This adapter deliberately exposes only rig inspect/build/validate. Use the direct
character export CLI for personas and packages, and the optional loopback voice API
for speech; these are not hidden MCP tools. [Voice/AIRI instructions](../prompts/voice-and-airi.md)
route those modes. The root Skill is `airi-character-forge`. The generic rig has no
motion authoring field; [DeskBot](../examples/deskbot/README.md) demonstrates explicit
project-owned motion3 post-processing. Validation of a generated project requires
its `build-manifest.json`; it is not a generic verifier for arbitrary downloaded models.
