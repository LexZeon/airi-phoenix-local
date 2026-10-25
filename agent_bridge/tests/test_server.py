# SPDX-License-Identifier: MIT
"""Run: python -m unittest discover -s agent_bridge/tests -v"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SERVER_PATH = Path(__file__).resolve().parents[1] / "server.py"
SPEC = importlib.util.spec_from_file_location("phoenix_mcp_server", SERVER_PATH)
assert SPEC and SPEC.loader
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)

STUB_RIG = '''import argparse, json, pathlib, sys, time
p=argparse.ArgumentParser()
p.add_argument("command", choices=["inspect","build","validate"])
p.add_argument("--project"); p.add_argument("--model"); p.add_argument("--out")
p.add_argument("--core-file"); p.add_argument("--json", action="store_true")
a=p.parse_args()
data=json.loads(pathlib.Path(a.project).read_text()) if a.project else {}
if data.get("delay"): time.sleep(1)
if data.get("invalid_stdout"): print("not-json"); sys.exit(0)
if a.command=="build":
    pathlib.Path(a.out).mkdir(parents=True, exist_ok=True)
    (pathlib.Path(a.out)/"built.txt").write_text("synthetic test")
ok=not data.get("fail")
print(json.dumps({"ok":ok,"stage":a.command,"code":"OK" if ok else "FIXTURE_FAILURE",
 "outputs":{"out":a.out},"summary":{"argv":sys.argv[1:]}}))
sys.exit(0 if ok else 3)
'''


class LocalFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="phoenix-mcp-test-")
        self.base = Path(self.temp.name)
        self.root = self.base / "workspace"
        self.root.mkdir()
        self.outside = self.base / "outside"
        self.outside.mkdir()
        self.stub = self.base / "stub_rig.py"
        self.stub.write_text(STUB_RIG, encoding="utf-8")
        self.core = self.outside / "Core.js"
        self.core.write_text("// synthetic fixture; never executed", encoding="utf-8")
        (self.root / "source.png").write_bytes(b"synthetic")
        self.project = self.root / "project.json"
        self.project.write_text(json.dumps({"sources": {"source": "source.png"}}), encoding="utf-8")
        (self.root / "sample.moc3").write_bytes(b"synthetic")
        self.model = self.root / "sample.model3.json"
        self.model.write_text(json.dumps({"FileReferences": {"Moc": "sample.moc3", "Textures": ["source.png"]}}), encoding="utf-8")
        self.runner = server.RigRunner(self.root, self.core, rig_script=self.stub)

    def tearDown(self):
        self.temp.cleanup()


class RunnerTests(LocalFixture):
    def test_fixed_argv_and_shell_metacharacters_are_data(self):
        unusual = self.root / "project ; echo NOT_A_COMMAND.json"
        unusual.write_bytes(self.project.read_bytes())
        result = self.runner.call("inspect", {"project": unusual.name})
        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"]["argv"], ["inspect", "--project", str(unusual), "--json"])
        self.assertFalse((self.root / "NOT_A_COMMAND").exists())

    def test_build_writes_only_new_output(self):
        result = self.runner.call("build", {"project": "project.json", "out": "generated"})
        self.assertTrue(result["ok"])
        self.assertTrue((self.root / "generated" / "built.txt").is_file())
        again = self.runner.call("build", {"project": "project.json", "out": "generated"})
        self.assertEqual(again["code"], "OUTPUT_NOT_EMPTY")
        self.assertEqual((self.root / "generated" / "built.txt").read_text(), "synthetic test")

    def test_validate_external_core_is_fixed_at_startup(self):
        result = self.runner.call("validate", {"model": "sample.model3.json"})
        self.assertTrue(result["ok"])
        self.assertIn(str(self.core), result["summary"]["argv"])
        forbidden = self.runner.call("validate", {"model": "sample.model3.json", "core_file": "other.js"})
        self.assertEqual(forbidden["code"], "INVALID_ARGUMENT")
        without_core = server.RigRunner(self.root, rig_script=self.stub).call("validate", {"model": "sample.model3.json"})
        self.assertEqual(without_core["code"], "CORE_NOT_CONFIGURED")

    def test_direct_absolute_parent_and_backslash_escape(self):
        for path in ("../outside/secret.json", "..\\outside\\secret.json", str(self.core), "file:///etc/passwd", "source.png:secret"):
            with self.subTest(path=path):
                result = self.runner.call("inspect", {"project": path})
                self.assertFalse(result["ok"])
                self.assertIn(result["code"], {"PATH_TRAVERSAL", "OUTSIDE_WORKSPACE", "INVALID_PATH"})

    def test_project_asset_root_and_source_escape(self):
        for data in ({"asset_root": "../outside", "sources": {}}, {"sources": {"secret": str(self.core)}}):
            self.project.write_text(json.dumps(data), encoding="utf-8")
            self.assertFalse(self.runner.call("inspect", {"project": "project.json"})["ok"])

    def test_model_nested_motion_and_expression_escape(self):
        for refs in ({"Moc": str(self.core)}, {"Motions": {"Idle": [{"File": str(self.core)}]}}, {"Expressions": [{"File": "../outside/Core.js"}]}):
            self.model.write_text(json.dumps({"FileReferences": refs}), encoding="utf-8")
            self.assertFalse(self.runner.call("validate", {"model": "sample.model3.json"})["ok"])

    def test_symlink_source_and_output_escape(self):
        link = self.root / "escape-link"
        try:
            link.symlink_to(self.outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            if sys.platform == "win32":
                import _winapi
                _winapi.CreateJunction(str(self.outside), str(link))
            else:
                self.skipTest("Platform does not permit test symlinks")
        self.project.write_text(json.dumps({"sources": {"secret": "escape-link/Core.js"}}), encoding="utf-8")
        self.assertEqual(self.runner.call("inspect", {"project": "project.json"})["code"], "OUTSIDE_WORKSPACE")
        self.project.write_text(json.dumps({"sources": {"source": "source.png"}}), encoding="utf-8")
        self.assertEqual(self.runner.call("build", {"project": "project.json", "out": "escape-link/new"})["code"], "OUTSIDE_WORKSPACE")

    def test_workspace_root_output_and_missing_inputs(self):
        self.assertEqual(self.runner.call("build", {"project": "project.json", "out": "."})["code"], "INVALID_OUTPUT")
        self.assertEqual(self.runner.call("inspect", {"project": "missing.json"})["code"], "PATH_NOT_FOUND")
        self.assertEqual(self.runner.call("inspect", {"project": "project.json", "extra": "x"})["code"], "INVALID_ARGUMENT")

    def test_child_failure_and_bad_json_remain_tool_errors(self):
        self.project.write_text(json.dumps({"fail": True}), encoding="utf-8")
        self.assertEqual(self.runner.call("inspect", {"project": "project.json"})["code"], "FIXTURE_FAILURE")
        self.project.write_text(json.dumps({"invalid_stdout": True}), encoding="utf-8")
        self.assertEqual(self.runner.call("inspect", {"project": "project.json"})["code"], "INVALID_RIG_OUTPUT")

    def test_child_timeout(self):
        self.project.write_text(json.dumps({"delay": True}), encoding="utf-8")
        self.runner.timeout = 0.05
        self.assertEqual(self.runner.call("inspect", {"project": "project.json"})["code"], "RIG_TIMEOUT")


class ProtocolTests(LocalFixture):
    def initialized_server(self):
        instance = server.Server(self.runner)
        initialized = instance.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}})
        self.assertEqual(initialized["result"]["protocolVersion"], "2025-11-25")
        self.assertIsNone(instance.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        return instance

    def test_initialize_list_call_and_structured_content(self):
        instance = self.initialized_server()
        result = instance.handle({"jsonrpc": "2.0", "id": "list", "method": "tools/list"})["result"]
        self.assertEqual([tool["name"] for tool in result["tools"]], ["inspect", "build", "validate"])
        self.assertTrue(result["tools"][0]["annotations"]["readOnlyHint"])
        self.assertFalse(result["tools"][1]["annotations"]["readOnlyHint"])
        call = instance.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "inspect", "arguments": {"project": "project.json"}}})["result"]
        self.assertFalse(call["isError"])
        self.assertEqual(json.loads(call["content"][0]["text"]), call["structuredContent"])

    def test_lifecycle_unknown_tool_and_parameter_errors(self):
        fresh = server.Server(self.runner)
        self.assertEqual(fresh.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["error"]["code"], -32002)
        instance = self.initialized_server()
        for params in ({"name": "delete"}, {"name": "inspect", "arguments": []}):
            self.assertEqual(instance.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": params})["error"]["code"], -32602)
        self.assertIsNone(instance.handle({"jsonrpc": "2.0", "method": "unknown-notification"}))
        tool_error = instance.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "inspect", "arguments": {"project": "../escape"}}})["result"]
        self.assertTrue(tool_error["isError"])

    def test_newer_client_gets_explicit_supported_legacy_version(self):
        instance = server.Server(self.runner)
        response = instance.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2026-07-28", "capabilities": {}, "clientInfo": {"name": "newer-client", "version": "1"}}})
        self.assertEqual(response["result"]["protocolVersion"], "2025-11-25")
        probe = server.Server(self.runner).handle({"jsonrpc": "2.0", "id": 2, "method": "server/discover"})
        self.assertEqual(probe["error"]["code"], -32601)

    def test_real_stdio_transport_stdout_is_only_protocol(self):
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "inspect", "arguments": {"project": "../forbidden"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "ping"},
        ]
        process = subprocess.run([sys.executable, str(SERVER_PATH), "--workspace", str(self.root)],
                                 input="\n".join(json.dumps(r) for r in requests) + "\n{bad json\n",
                                 capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        replies = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual(len(replies), 5)
        self.assertEqual([reply["id"] for reply in replies], [1, 2, 3, 4, None])
        self.assertTrue(replies[2]["result"]["isError"])
        self.assertEqual(replies[-1]["error"]["code"], -32700)

    def test_duplicate_keys_and_nonfinite_numbers_are_rejected(self):
        for value in ('{"a":1,"a":2}', '{"a":NaN}'):
            with self.assertRaises(ValueError):
                server.strict_json(value)

    def test_invalid_startup_keeps_stdout_empty(self):
        process = subprocess.run([sys.executable, str(SERVER_PATH), "--workspace", str(self.root / "missing")],
                                 capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(process.returncode, 2)
        self.assertEqual(process.stdout, "")
        self.assertTrue(process.stderr)

    def test_oversized_input_closes_without_nonprotocol_stdout(self):
        process = subprocess.run([sys.executable, str(SERVER_PATH), "--workspace", str(self.root)],
                                 input="x" * (server.MAX_MESSAGE_BYTES + 1) + "\n",
                                 capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(process.returncode, 2)
        self.assertEqual(process.stdout, "")
        self.assertIn("exceeded", process.stderr)

    def test_invalid_initialize_and_request_ids(self):
        instance = server.Server(self.runner)
        invalid = instance.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {}}})
        self.assertEqual(invalid["error"]["code"], -32602)
        for request_id in (None, True, [], {}):
            invalid_id = instance.handle({"jsonrpc": "2.0", "id": request_id, "method": "ping"})
            self.assertEqual(invalid_id["error"]["code"], -32600)


if __name__ == "__main__":
    unittest.main()
