#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise the actual builder through MCP; Core remains an external local file."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path, help="Original bundled sample project JSON")
    parser.add_argument("--core-file", required=True, type=Path, help="Your explicitly authorized local Core.js (not copied)")
    parser.add_argument("--node", type=Path, help="Optional Node executable; prepends its directory for this child only")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    server = here.parent / "server.py"
    started = time.monotonic()
    report: dict = {
        "test": "agent-bridge-real-rig-fixture", "testedAt": datetime.now(timezone.utc).isoformat(),
        "protocolVersion": "2025-11-25", "transport": "stdio", "ok": False,
        "fixture": "Bundled original robot geometry; copied into an isolated temporary workspace.",
        "core": "Explicit external local file, not copied or bundled.", "calls": [],
    }
    process = None
    try:
        project = args.project.resolve(strict=True)
        core = args.core_file.resolve(strict=True)
        environment = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        if args.node:
            environment["PATH"] = str(args.node.resolve(strict=True).parent) + os.pathsep + environment.get("PATH", "")
        with tempfile.TemporaryDirectory(prefix="phoenix-mcp-real-") as temp:
            workspace = Path(temp)
            fixture = workspace / "fixture"
            shutil.copytree(project.parent, fixture, symlinks=False)
            local_project = fixture / project.name
            process = subprocess.Popen(
                [sys.executable, str(server), "--workspace", str(workspace), "--core-file", str(core)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8", bufsize=1, env=environment,
            )
            replies: queue.Queue = queue.Queue()

            def read_protocol():
                try:
                    for line in process.stdout:
                        replies.put(json.loads(line))
                except (ValueError, OSError):
                    replies.put({"invalid_protocol": True})

            threading.Thread(target=read_protocol, daemon=True).start()
            next_id = 0

            def send(method: str, params: dict | None = None, notification=False):
                nonlocal next_id
                request = {"jsonrpc": "2.0", "method": method}
                if not notification:
                    next_id += 1
                    request["id"] = next_id
                if params is not None:
                    request["params"] = params
                process.stdin.write(json.dumps(request) + "\n")
                process.stdin.flush()
                if notification:
                    return None
                response = replies.get(timeout=330)
                if response.get("id") != next_id or "error" in response or "result" not in response:
                    raise RuntimeError("PROTOCOL_ERROR")
                return response["result"]

            initialized = send("initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "phoenix-real-fixture-test", "version": "1"}})
            if initialized["protocolVersion"] != "2025-11-25":
                raise RuntimeError("WRONG_PROTOCOL_VERSION")
            send("notifications/initialized", notification=True)
            tools = send("tools/list")["tools"]
            report["listedTools"] = [tool["name"] for tool in tools]

            def call(name: str, arguments: dict):
                began = time.monotonic()
                result = send("tools/call", {"name": name, "arguments": arguments})
                structured = result["structuredContent"]
                report["calls"].append({
                    "tool": name, "ok": structured.get("ok"), "stage": structured.get("stage"),
                    "code": structured.get("code"), "isError": result.get("isError"),
                    "structuredTextMatch": json.loads(result["content"][0]["text"]) == structured,
                    "elapsedSeconds": round(time.monotonic() - began, 3),
                })
                if not structured.get("ok") or result.get("isError"):
                    raise RuntimeError("FIXTURE_" + name.upper() + "_FAILED")
                return structured

            call("inspect", {"project": str(local_project)})
            call("build", {"project": str(local_project), "out": "build"})
            models = list((workspace / "build").rglob("*.model3.json"))
            if len(models) != 1:
                raise RuntimeError("EXPECTED_ONE_BUILT_MODEL")
            report["modelFilename"] = models[0].name
            report["generatedFileCount"] = sum(1 for file in (workspace / "build").rglob("*") if file.is_file())
            call("validate", {"model": str(models[0])})
            # Real boundary error over stdio, without touching any external file.
            rejected = send("tools/call", {"name": "inspect", "arguments": {"project": "../outside.json"}})
            report["traversalRejected"] = rejected.get("isError") is True and rejected["structuredContent"].get("code") == "PATH_TRAVERSAL"
            report["ok"] = report["traversalRejected"] and all(call["structuredTextMatch"] for call in report["calls"])
            process.stdin.close()
            process.wait(timeout=10)
    except Exception as error:
        # Keep local paths, raw Core diagnostics, and input art out of public reports.
        report["error"] = str(error) if isinstance(error, RuntimeError) else type(error).__name__
    finally:
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        report["elapsedSeconds"] = round(time.monotonic() - started, 3)
        report["limitations"] = ["Core validation is separate from visual acceptance in AIRI."]
        (here / "real-fixture-test-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
