#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify local voice HTTP behavior with fixed original synthetic text only."""

import argparse
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid
import wave


def request(url, data=None, method=None):
    headers = {"Content-Type": "application/json"} if data is not None else {}
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    began = time.monotonic()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers, method=method), timeout=180) as response:
            return response.status, response.read(), dict(response.headers), time.monotonic() - began
    except urllib.error.HTTPError as error:
        return error.code, error.read(), dict(error.headers), time.monotonic() - began


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:9945")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = {"ok": False, "testedAt": datetime.now(timezone.utc).isoformat(), "service": "airi-phoenix-qwen-tts", "checks": []}
    try:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            status, body, _headers, _elapsed = request(args.url + "/health")
            health = json.loads(body)
            if status == 200 and health.get("ready"):
                break
            time.sleep(2)
        else:
            raise RuntimeError("SERVICE_NOT_READY")
        if health["service"] != "airi-phoenix-qwen-tts":
            raise RuntimeError("WRONG_SERVICE")
        model = health["model"]

        def check(name, ok, **details):
            report["checks"].append({"name": name, "ok": bool(ok), **details})

        for endpoint in ("/health", "/v1/models", "/v1/audio/voices"):
            status, body, headers, _elapsed = request(args.url + endpoint)
            check("GET " + endpoint, status == 200 and headers.get("Access-Control-Allow-Origin") == "*")
            json.loads(body)
        status, _body, headers, _elapsed = request(args.url + "/health", method="HEAD")
        check("HEAD health", status == 200 and headers.get("Access-Control-Allow-Origin") == "*")
        status, _body, headers, _elapsed = request(args.url + "/v1/audio/speech", method="OPTIONS")
        check("CORS preflight", status == 204 and headers.get("Access-Control-Allow-Origin") == "*")
        invalids = [
            ("unknown-model", {"model": "not-a-model", "input": "合成测试"}),
            ("unknown-voice", {"model": model, "input": "合成测试", "voice": "not-a-voice", "response_format": "wav"}),
            ("empty-input", {"model": model, "input": "", "response_format": "wav"}),
            ("unsupported-format", {"model": model, "input": "合成测试", "response_format": "unknown"}),
        ]
        for name, payload in invalids:
            status, body, _headers, _elapsed = request(args.url + "/v1/audio/speech", payload)
            check(name, status == 400 and "error" in json.loads(body))
        for audio_format in ("wav", "mp3"):
            status, body, headers, elapsed = request(args.url + "/v1/audio/speech", {
                "model": model, "input": "收到，稍等一下。", "voice": "phoenix-focused", "response_format": audio_format,
            })
            valid = status == 200 and len(body) > 100
            if audio_format == "wav" and valid:
                with wave.open(io.BytesIO(body), "rb") as audio:
                    valid = audio.getframerate() == 24000 and audio.getnchannels() == 1 and audio.getnframes() > 0
            if audio_format == "mp3" and valid:
                valid = body.startswith(b"ID3") or body[0] == 255 and body[1] & 224 == 224
            check("POST actual " + audio_format, valid, bytes=len(body), wall_seconds=round(elapsed, 4),
                  audio_seconds=headers.get("X-AIRI-Audio-Seconds"), generation_seconds=headers.get("X-AIRI-Generation-Seconds"))
        final = json.loads(request(args.url + "/health")[1])
        report["metrics"] = final["metrics"]
        report["network"] = final["network"]
        report["ok"] = all(item["ok"] for item in report["checks"]) and final["network"]["blocked_attempts"] == 0
    except Exception as error:
        report["error_type"] = type(error).__name__
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
