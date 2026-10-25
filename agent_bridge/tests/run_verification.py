#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run adapter tests and write a shareable report without temporary host paths."""

from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import time
import unittest

tests = Path(__file__).resolve().parent
started = time.monotonic()
suite = unittest.defaultTestLoader.discover(str(tests), pattern="test_*.py")
stream = io.StringIO()
result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
report = {
    "test": "agent-bridge-protocol-and-file-boundary",
    "testedAt": datetime.now(timezone.utc).isoformat(),
    "protocolVersion": "2025-11-25",
    "transport": "stdio",
    "python": ".".join(map(str, sys.version_info[:3])),
    "testsRun": result.testsRun,
    "failures": len(result.failures),
    "errors": len(result.errors),
    "skipped": len(result.skipped),
    "elapsedSeconds": round(time.monotonic() - started, 3),
    "ok": result.wasSuccessful(),
    "scope": [
        "real subprocess stdio initialize/tools-list/tools-call/ping/parse-error",
        "structuredContent and text JSON parity",
        "fixed shell-free child argv and synthetic filenames",
        "project/asset/model/output traversal and external paths",
        "symlink or Windows junction escape",
        "single startup-authorized external Core file",
        "nonempty output preservation",
        "child error/invalid JSON/timeout",
    ],
    "fixture": "Synthetic temporary inputs and stub rig; no private media or account data.",
    "limitations": ["Builder/Core integration is recorded separately.", "Application-level path checks are not an operating-system sandbox."],
}
output = tests / "protocol-test-report.json"
output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
if not result.wasSuccessful():
    print("Test IDs failed:", file=sys.stderr)
    for case, _traceback in result.failures + result.errors:
        print(case.id(), file=sys.stderr)
sys.exit(0 if result.wasSuccessful() else 1)
