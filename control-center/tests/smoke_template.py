#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise the sanitized console against synthetic files and an isolated loopback port."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import urllib.error
import urllib.request


def main():
    root = Path(__file__).resolve().parents[1]
    checks = []
    with tempfile.TemporaryDirectory(prefix="airi-console-template-") as temporary:
        data = Path(temporary)
        settings = data/"deployment/offline-settings.json"
        settings.parent.mkdir(parents=True)
        original = {"revision": "synthetic-original", "character": {"id": "original-fixture", "keep": True},
            "unrelated": {"sentinel": "preserve"}, "providers": {}, "storage": {"unrelated/key": "preserve"},
            "additionalCharacters": [{"id": "second-fixture", "modelZip": "private/second.zip", "activate": False},
                {"id": "third-fixture-3d", "modelZip": "private/third.zip", "activate": True}]}
        raw = json.dumps(original).encode()
        settings.write_bytes(raw)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        os.environ.update(AIRI_COMPANIONS_ROOT=str(data/"deployment"), AIRI_OFFLINE_SETTINGS=str(settings),
            AIRI_CONTROL_DATA_DIR=str(data/"private-state"), AIRI_CONTROL_PORT=str(port),
            AIRI_MODELS_ROOT=str(data/"absent-models"), AIRI_WORKBENCH=str(data/"absent-workbench"))
        sys.path.insert(0, str(root))
        profiles = importlib.import_module("profiles")
        server = importlib.import_module("server")
        assert profiles.SETTINGS == settings and profiles.DATA_ROOT == data/"private-state"
        assert server.APP_ID == "airi-local-control-center" and server.PORT == port
        checks.append("environment paths and port select only the isolated fixture")
        profile = {"selections": dict(profiles.DEFAULT), "custom": {}}
        for bad in ("http://example.org/v1/", "http://169.254.169.254/", f"http://127.0.0.1:{port}/api/"):
            try:
                profiles.local_url(bad)
                raise AssertionError("unsafe endpoint accepted")
            except ValueError:
                pass
        checks.append("external metadata and own-console model endpoints rejected")
        httpd = server.ThreadingHTTPServer(("127.0.0.1", port), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{port}"

        def request(path, body=None, csrf=None, origin=None):
            headers = {}
            if body is not None:
                headers["Content-Type"] = "application/json"
            if csrf:
                headers["X-Control-CSRF"] = csrf
            if origin:
                headers["Origin"] = origin
            req = urllib.request.Request(base+path, json.dumps(body).encode() if body is not None else None, headers)
            try:
                with urllib.request.urlopen(req, timeout=4) as response:
                    return response.status, json.load(response)
            except urllib.error.HTTPError as error:
                return error.code, json.load(error)

        try:
            status, health = request("/health")
            assert status == 200 and health["app"] == "airi-local-control-center"
            status, bootstrap = request("/api/bootstrap")
            assert status == 200 and bootstrap["csrfToken"]
            csrf = bootstrap["csrfToken"]
            checks.append("isolated HTTP health and bootstrap are real")
            status, _ = request("/api/preferences", {"profile": profile}, origin=base)
            assert status == 403
            status, _ = request("/api/preferences", {"profile": profile}, csrf, "http://example.org")
            assert status == 403
            checks.append("missing CSRF and cross-origin writes rejected")
            status, result = request("/api/preferences", {"profile": profile}, csrf, base)
            assert status == 200 and result["ok"] and settings.read_bytes() == raw
            checks.append("preference save does not modify AIRI settings")
            status, result = request("/api/apply", {"profile": profile}, csrf, base)
            assert status == 200 and result["ok"]
            applied = json.loads(settings.read_bytes())
            assert applied["unrelated"] == original["unrelated"]
            assert applied["character"]["id"] == "original-fixture" and applied["character"]["keep"]
            assert applied["storage"]["unrelated/key"] == "preserve"
            assert len(applied["character"]["modulesOverride"]) == 4
            for before, after in zip(original["additionalCharacters"], applied["additionalCharacters"]):
                assert after["modelZip"] == before["modelZip"] and after["activate"] == before["activate"]
                assert after["modulesOverride"] == applied["character"]["modulesOverride"]
                assert after["selectionRevision"] == applied["revision"]
            checks.append("all three managed cards receive new modules and revision while model paths and activation are preserved")
            backups = list(settings.parent.glob("offline-settings.json.*.bak"))
            assert len(backups) == 1 and hashlib.sha256(backups[0].read_bytes()).digest() == hashlib.sha256(raw).digest()
            checks.append("actual fixture apply preserves character and unrelated settings with exact backup")
            status, _ = request("/api/action", {"action": "arbitrary-command"}, csrf, base)
            assert status == 400
            checks.append("arbitrary launcher action rejected")
        finally:
            httpd.shutdown()
            thread.join(timeout=4)
            httpd.server_close()
    report = {"ok": True, "scope": "Published parameterized template, synthetic settings, isolated local HTTP; no real AIRI settings or model processes touched",
        "checks": checks, "checksPassed": len(checks), "liveAiriRestarted": False,
        "privatePathsOrSettingsIncluded": False, "uiRetested": False,
        "uiEvidence": "Historical deployed-console checks are separate in ../verification-summary.json"}
    (root/"tests/template-verification.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
