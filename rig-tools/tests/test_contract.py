"""MIT. CLI/schema and missing-runtime regressions using the original robot."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="layered-rig-test-")
        self.root = Path(self.temp.name)
        shutil.copytree(TOOL/"examples/robot", self.root/"project")
        self.project = self.root/"project/project.json"

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args):
        completed = subprocess.run([sys.executable, str(TOOL/"rig.py"), *map(str, args), "--json"], capture_output=True, text=True, encoding="utf-8")
        payload = json.loads(completed.stdout)
        self.assertIsInstance(payload["code"], str)
        self.assertIsInstance(payload["outputs"], list)
        return completed.returncode, payload

    def build_robot(self):
        code, payload = self.run_cli("build", "--project", self.project, "--out", self.root/"output")
        self.assertEqual(code, 0, payload)
        return self.root/"output/RobotDemo.model3.json"

    def test_unknown_top_and_layer_fields_are_rejected(self):
        original = json.loads(self.project.read_text())
        for nested in (False, True):
            spec = json.loads(json.dumps(original))
            (spec["layers"][0] if nested else spec)["unsupported_test_field"] = True
            self.project.write_text(json.dumps(spec))
            code, payload = self.run_cli("inspect", "--project", self.project)
            self.assertEqual((code, payload["ok"], payload["code"]), (2, False, "PROJECT_SCHEMA"))

    def test_real_template_can_init_inspect_and_build(self):
        code, payload = self.run_cli("init", "--out", self.root/"new", "--name", "IndependentRobot")
        self.assertEqual(code, 0, payload)
        code, payload = self.run_cli("inspect", "--project", self.root/"new/project.json")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["summary"]["name"], "IndependentRobot")
        self.assertTrue(self.build_robot().is_file())

    def test_missing_texture_expression_motion_and_sound_fail_before_core(self):
        model = self.build_robot()
        original = json.loads(model.read_text())
        for category in ("texture", "expression", "motion", "sound"):
            settings = json.loads(json.dumps(original))
            if category == "texture":
                settings["FileReferences"]["Textures"] = ["absent.png"]
            elif category == "expression":
                settings["FileReferences"]["Expressions"][0]["File"] = "absent.exp3.json"
            elif category == "motion":
                settings["FileReferences"]["Motions"] = {"Idle": [{"File": "absent.motion3.json"}]}
            else:
                (model.parent/"present.motion3.json").write_text('{"Version":3,"Curves":[]}')
                settings["FileReferences"]["Motions"] = {"Idle": [{"File": "present.motion3.json", "Sound": "absent.wav"}]}
            model.write_text(json.dumps(settings))
            code, payload = self.run_cli("validate", "--model", model)
            self.assertEqual((code, payload["code"]), (4, "RUNTIME_REFERENCE_MISSING"), payload)

    def test_reference_traversal_and_bad_png_are_rejected(self):
        model = self.build_robot()
        settings = json.loads(model.read_text())
        settings["FileReferences"]["Textures"] = ["../outside.png"]
        model.write_text(json.dumps(settings))
        code, payload = self.run_cli("validate", "--model", model)
        self.assertEqual((code, payload["code"]), (4, "RUNTIME_REFERENCE_UNSAFE"))
        settings["FileReferences"]["Textures"] = ["broken.png"]
        (model.parent/"broken.png").write_bytes(b"not a PNG")
        model.write_text(json.dumps(settings))
        code, payload = self.run_cli("validate", "--model", model)
        self.assertEqual((code, payload["code"]), (4, "RUNTIME_REFERENCE_INVALID"))

    def test_argument_errors_are_machine_readable(self):
        code, payload = self.run_cli("validate")
        self.assertEqual((code, payload["code"]), (2, "ARGUMENT_INVALID"))

    @unittest.skipUnless(os.environ.get("LIVE2D_CORE_FILE"), "Supply a licensed Core for the integration test")
    def test_core_accepts_real_robot_and_validation_is_read_only(self):
        model = self.build_robot()
        before = {str(p.relative_to(model.parent)): (p.stat().st_size, p.stat().st_mtime_ns) for p in model.parent.rglob("*") if p.is_file()}
        code, payload = self.run_cli("validate", "--model", model, "--core-file", os.environ["LIVE2D_CORE_FILE"], "--node-executable", os.environ.get("NODE", "node"))
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["summary"]["status"], "PASS")
        self.assertEqual(payload["outputs"], [])
        after = {str(p.relative_to(model.parent)): (p.stat().st_size, p.stat().st_mtime_ns) for p in model.parent.rglob("*") if p.is_file()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
