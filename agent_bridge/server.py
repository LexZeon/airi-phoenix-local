#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""MCP 2025-11-25 stdio adapter. No sockets, downloads, shell, or account SDKs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

PROTOCOL_VERSION = "2025-11-25"
VERSION = "0.1.0"
MAX_MESSAGE_BYTES = 1024 * 1024
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_RESULT_BYTES = 4 * 1024 * 1024
RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "stage": {"type": "string"},
        "code": {"type": "string"},
        "outputs": {},
        "summary": {},
    },
    "required": ["ok", "stage", "code", "outputs", "summary"],
}


def strict_json(text: str) -> Any:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON object key")
            result[key] = value
        return result

    def invalid_constant(_value: str) -> None:
        raise ValueError("Non-finite JSON number")

    return json.loads(text, object_pairs_hook=unique_pairs, parse_constant=invalid_constant)


class ToolFailure(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class RpcFailure(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def failure(stage: str, code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "stage": stage, "code": code, "outputs": {}, "summary": message}


class Workspace:
    """Resolve every user-controlled file through one canonical local root."""

    def __init__(self, root: Path):
        self.root = root.expanduser().resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("--workspace must be an existing directory")

    @staticmethod
    def clean(value: Any) -> str:
        if not isinstance(value, str) or not value or len(value) > 4096:
            raise ToolFailure("INVALID_PATH", "A nonempty local path of at most 4096 characters is required.")
        if any(ord(character) < 32 for character in value):
            raise ToolFailure("INVALID_PATH", "Control characters are not allowed in paths.")
        normalized = value.replace("\\", "/")
        if ".." in normalized.split("/"):
            raise ToolFailure("PATH_TRAVERSAL", "Parent traversal (..) is not allowed.")
        # Permit the Windows drive separator only; deny ADS, URLs, and device namespaces.
        rest = normalized[2:] if len(normalized) > 1 and normalized[1] == ":" and normalized[0].isalpha() else normalized
        if ":" in rest or normalized.startswith(("//?", "//.")):
            raise ToolFailure("INVALID_PATH", "URLs, device paths, and alternate data streams are not allowed.")
        if os.name != "nt" and "\\" in value:
            raise ToolFailure("INVALID_PATH", "Use native or forward-slash paths on this platform.")
        return value

    def resolve(self, value: Any, *, relative_to: Path | None = None,
                must_exist: bool = True, directory: bool = False) -> Path:
        clean = self.clean(value)
        candidate = Path(clean)
        if not candidate.is_absolute():
            candidate = (relative_to or self.root) / candidate
        try:
            canonical = candidate.resolve(strict=must_exist)
        except (OSError, RuntimeError) as exc:
            raise ToolFailure("PATH_NOT_FOUND", "The requested local path cannot be resolved.") from exc
        if not canonical.is_relative_to(self.root):
            raise ToolFailure("OUTSIDE_WORKSPACE", "The path or a symlink/junction resolves outside --workspace.")
        if must_exist and (not canonical.is_dir() if directory else not canonical.is_file()):
            raise ToolFailure("WRONG_PATH_TYPE", "Expected a local directory." if directory else "Expected a local file.")
        return canonical

    def json_file(self, file: Path) -> dict[str, Any]:
        try:
            if file.stat().st_size > MAX_JSON_BYTES:
                raise ToolFailure("JSON_TOO_LARGE", "JSON input exceeds the 8 MiB limit.")
            data = strict_json(file.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise ToolFailure("INVALID_JSON_FILE", "The input must be a valid UTF-8 JSON object.") from exc
        if not isinstance(data, dict):
            raise ToolFailure("INVALID_JSON_FILE", "The input must be a JSON object.")
        return data

    def project(self, value: Any) -> Path:
        project = self.resolve(value)
        data = self.json_file(project)
        asset_root = self.resolve(data.get("asset_root", "."), relative_to=project.parent, directory=True)
        sources = data.get("sources", {})
        if not isinstance(sources, dict):
            raise ToolFailure("INVALID_PROJECT", "project.sources must be an object of local image paths.")
        for alias, source in sources.items():
            if not isinstance(alias, str) or not isinstance(source, str):
                raise ToolFailure("INVALID_PROJECT", "Every source must map an alias to a local image path.")
            # Absolute paths inside the workspace are safe, but relative paths may
            # not climb out of the asset root through a symbolic link either.
            resolved = self.resolve(source, relative_to=asset_root)
            if not resolved.is_relative_to(asset_root):
                raise ToolFailure("OUTSIDE_ASSET_ROOT", "A source resolves outside project.asset_root.")
        return project

    def model(self, value: Any) -> Path:
        model = self.resolve(value)
        if not model.name.endswith(".model3.json"):
            raise ToolFailure("INVALID_MODEL", "model must name a .model3.json file.")
        data = self.json_file(model)
        references = data.get("FileReferences", {})
        if not isinstance(references, dict):
            raise ToolFailure("INVALID_MODEL", "model.FileReferences must be an object.")

        def check_references(node: Any) -> None:
            if isinstance(node, str):
                self.resolve(node, relative_to=model.parent)
            elif isinstance(node, list):
                for item in node:
                    check_references(item)
            elif isinstance(node, dict):
                for item in node.values():
                    check_references(item)
            elif node is not None and not isinstance(node, (bool, int, float)):
                raise ToolFailure("INVALID_MODEL", "Invalid model file reference.")

        # Only path-bearing model fields; model metadata and parameter names are data.
        for field in ("Moc", "Textures", "Physics", "Pose", "UserData", "DisplayInfo"):
            if field in references:
                check_references(references[field])
        for expression in references.get("Expressions", []):
            if isinstance(expression, dict) and "File" in expression:
                check_references(expression["File"])
        motions = references.get("Motions", {})
        if not isinstance(motions, dict):
            raise ToolFailure("INVALID_MODEL", "model.FileReferences.Motions must be an object.")
        for group in motions.values():
            if not isinstance(group, list):
                raise ToolFailure("INVALID_MODEL", "Each motion group must be an array.")
            for motion in group:
                if isinstance(motion, dict):
                    for field in ("File", "Sound"):
                        if field in motion:
                            check_references(motion[field])
        return model

    def output(self, value: Any) -> Path:
        output = self.resolve(value, must_exist=False)
        if output == self.root:
            raise ToolFailure("INVALID_OUTPUT", "Use a new subdirectory, not the workspace root.")
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise ToolFailure("OUTPUT_NOT_EMPTY", "Build output must be a new or empty directory; existing files are preserved.")
        return output


class RigRunner:
    def __init__(self, workspace: Path, core_file: Path | None = None,
                 timeout: float = 300, rig_script: Path | None = None):
        self.workspace = Workspace(workspace)
        self.rig_script = rig_script or Path(__file__).resolve().parents[1] / "rig-tools" / "rig.py"
        self.timeout = timeout
        self.core_file = core_file.expanduser().resolve(strict=True) if core_file else None
        if self.core_file and (not self.core_file.is_file() or self.core_file.suffix.lower() != ".js"):
            raise ValueError("--core-file must name one existing JavaScript Core file")

    @staticmethod
    def tools() -> list[dict[str, Any]]:
        definitions = [
            ("inspect", "Inspect rig project", "Inspect a local project and its source images without modifying files.", {"project": {"type": "string", "description": "Project JSON path inside --workspace."}}, ["project"], True),
            ("build", "Build local Live2D rig", "Build a local project into a new or empty output directory inside --workspace. No publishing or downloads.", {"project": {"type": "string"}, "out": {"type": "string", "description": "New or empty output directory inside --workspace."}}, ["project", "out"], False),
            ("validate", "Validate local Live2D model", "Validate a local .model3.json and referenced files. Uses only the Core file explicitly allowed when this server started.", {"model": {"type": "string", "description": ".model3.json path inside --workspace."}}, ["model"], True),
        ]
        return [{
            "name": name, "title": title, "description": description,
            "inputSchema": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
            "outputSchema": RESULT_SCHEMA,
            "annotations": {"readOnlyHint": read_only, "destructiveHint": False,
                            "idempotentHint": read_only, "openWorldHint": False},
        } for name, title, description, properties, required, read_only in definitions]

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        expected = {"inspect": {"project"}, "build": {"project", "out"}, "validate": {"model"}}[name]
        if set(arguments) != expected or any(not isinstance(value, str) for value in arguments.values()):
            return failure(name, "INVALID_ARGUMENT", "Supply exactly these string arguments: " + ", ".join(sorted(expected)))
        try:
            if name in ("inspect", "build"):
                project = self.workspace.project(arguments["project"])
                args = [name, "--project", str(project)]
                if name == "build":
                    args += ["--out", str(self.workspace.output(arguments["out"]))]
            else:
                model = self.workspace.model(arguments["model"])
                if self.core_file is None:
                    raise ToolFailure("CORE_NOT_CONFIGURED", "Start the adapter with --core-file pointing to your licensed local Core.js.")
                args = [name, "--model", str(model), "--core-file", str(self.core_file)]
            if not self.rig_script.is_file():
                raise ToolFailure("RIG_NOT_INSTALLED", "The bundled rig-tools/rig.py is missing.")
            # Neither tool arguments nor project contents become shell code.
            process = subprocess.run(
                [sys.executable, "-I", str(self.rig_script), *args, "--json"],
                cwd=self.workspace.root, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding="utf-8", errors="replace", timeout=self.timeout,
                shell=False, env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
            )
            # Rig stderr is never reflected to the agent (it can contain local data).
            if len(process.stdout.encode("utf-8")) > MAX_RESULT_BYTES:
                raise ToolFailure("RIG_OUTPUT_TOO_LARGE", "Rig output exceeds the 4 MiB limit.")
            try:
                payload = strict_json(process.stdout)
            except ValueError as exc:
                raise ToolFailure("INVALID_RIG_OUTPUT", "Rig CLI did not return one JSON object.") from exc
            if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
                raise ToolFailure("INVALID_RIG_OUTPUT", "Rig CLI result is missing a boolean ok field.")
            for key in ("stage", "code"):
                if not isinstance(payload.get(key), str):
                    raise ToolFailure("INVALID_RIG_OUTPUT", "Rig CLI result has an invalid " + key + " field.")
            if not all(key in payload for key in ("outputs", "summary")):
                raise ToolFailure("INVALID_RIG_OUTPUT", "Rig CLI result is missing outputs or summary.")
            if process.returncode and payload["ok"]:
                raise ToolFailure("RIG_EXIT_MISMATCH", "Rig CLI returned an error exit code with ok=true.")
            return payload
        except ToolFailure as exc:
            return failure(name, exc.code, str(exc))
        except subprocess.TimeoutExpired:
            return failure(name, "RIG_TIMEOUT", "Rig CLI exceeded the configured timeout.")
        except (OSError, ValueError, TypeError):
            return failure(name, "LOCAL_IO_ERROR", "A local file or subprocess operation failed; check the project and Python dependencies.")


class Server:
    def __init__(self, runner: RigRunner):
        self.runner = runner
        self.initialized = False
        self.ready = False

    def handle(self, request: Any) -> dict[str, Any] | None:
        request_id: str | int | None = None
        notification = False
        try:
            if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
                raise RpcFailure(-32600, "Invalid JSON-RPC request")
            notification = "id" not in request
            request_id = request.get("id")
            if not notification and (isinstance(request_id, bool) or not isinstance(request_id, (str, int))):
                request_id = None
                raise RpcFailure(-32600, "Request ID must be a string or integer")
            params = request.get("params", {})
            if not isinstance(params, dict):
                raise RpcFailure(-32602, "params must be an object")
            method = request["method"]
            if notification:
                if method == "notifications/initialized" and self.initialized:
                    self.ready = True
                return None
            if method == "ping":
                result: dict[str, Any] = {}
            elif method == "initialize":
                if self.initialized:
                    raise RpcFailure(-32600, "Already initialized")
                client_info = params.get("clientInfo")
                if (not isinstance(params.get("protocolVersion"), str)
                        or not isinstance(params.get("capabilities"), dict)
                        or not isinstance(client_info, dict)
                        or not all(isinstance(client_info.get(key), str) for key in ("name", "version"))):
                    raise RpcFailure(-32602, "initialize requires protocolVersion, capabilities, and clientInfo")
                self.initialized = True
                result = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "airi-phoenix-local-rig", "version": VERSION},
                    "instructions": "Local rig tools only. Paths and referenced assets must stay inside the workspace selected by the human. Build uses a new or empty directory. No downloads, publishing, or file deletion.",
                }
            elif method == "server/discover":
                # Deliberately legacy: modern clients can probe and fall back.
                raise RpcFailure(-32601, "This server implements legacy MCP 2025-11-25; use initialize")
            else:
                if not self.ready:
                    raise RpcFailure(-32002, "Send initialize and notifications/initialized first")
                if method == "tools/list":
                    if "cursor" in params:
                        raise RpcFailure(-32602, "This fixed tool list has no pagination cursor")
                    result = {"tools": self.runner.tools()}
                elif method == "tools/call":
                    name = params.get("name")
                    if not isinstance(name, str) or name not in {"inspect", "build", "validate"}:
                        raise RpcFailure(-32602, "Unknown tool")
                    arguments = params.get("arguments", {})
                    if not isinstance(arguments, dict):
                        raise RpcFailure(-32602, "arguments must be an object")
                    payload = self.runner.call(name, arguments)
                    result = {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, allow_nan=False)}],
                              "structuredContent": payload, "isError": not payload["ok"]}
                else:
                    raise RpcFailure(-32601, "Method not found")
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except RpcFailure as exc:
            return None if notification else {"jsonrpc": "2.0", "id": request_id, "error": {"code": exc.code, "message": str(exc)}}


def serve(server: Server) -> int:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    while True:
        line = stdin.readline(MAX_MESSAGE_BYTES + 1)
        if not line:
            return 0
        if len(line) > MAX_MESSAGE_BYTES:
            # Do not attempt to parse a later fragment as an independent message.
            print("MCP input exceeded 1 MiB; closing stdio.", file=sys.stderr)
            return 2
        try:
            request = strict_json(line.decode("utf-8"))
            response = server.handle(request)
        except (UnicodeError, ValueError):
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        except Exception:
            # No traceback or raw input on stdout/stderr.
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": "Internal server error"}}
            print("MCP request failed internally.", file=sys.stderr)
        if response is not None:
            stdout.write((json.dumps(response, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8"))
            stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path, help="Existing directory explicitly allowed for local rig files and outputs")
    parser.add_argument("--core-file", type=Path, help="Explicitly allow this one licensed local Core.js, even outside --workspace")
    parser.add_argument("--timeout", type=float, default=300, help="Per-tool subprocess timeout in seconds (1..3600)")
    args = parser.parse_args()
    if not 1 <= args.timeout <= 3600:
        parser.error("--timeout must be between 1 and 3600 seconds")
    try:
        runner = RigRunner(args.workspace, args.core_file, args.timeout)
    except (OSError, ValueError):
        print("Invalid startup path: workspace must exist; Core must be one existing .js file.", file=sys.stderr)
        return 2
    try:
        return serve(Server(runner))
    except (BrokenPipeError, KeyboardInterrupt):
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
