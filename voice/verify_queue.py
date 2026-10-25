#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Synthetic bounded-queue, disconnect cleanup, and concurrent-chunk test."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import time
import urllib.error
import urllib.request


def health():
    with urllib.request.urlopen("http://127.0.0.1:9945/health", timeout=5) as response:
        return json.load(response)


def synthesize(text):
    data = json.dumps({"model": "phoenix-qwen3-tts-local", "input": text,
                       "voice": "phoenix-focused", "response_format": "wav"}, ensure_ascii=False).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:9945/v1/audio/speech", data=data,
                                                          headers={"Content-Type": "application/json"}), timeout=150) as response:
            audio = response.read()
            return {"status": response.status, "audio_bytes": len(audio), "wave_header": audio.startswith(b"RIFF")}
    except urllib.error.HTTPError as error:
        error.read()
        return {"status": error.code}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = {"ok": False, "testedAt": datetime.now(timezone.utc).isoformat(), "test": "bounded-local-voice-queue", "syntheticOnly": True}
    peers = []
    try:
        deadline = time.monotonic() + 180
        while not health().get("ready"):
            if time.monotonic() > deadline:
                raise RuntimeError("MODEL_NOT_READY")
            time.sleep(1)
        before = health()
        body = json.dumps({"model": "phoenix-qwen3-tts-local", "input": "这是固定的本机合成排队取消测试，请保持平稳语速，一二三四五六七八九十。",
                           "voice": "phoenix-focused", "response_format": "wav"}, ensure_ascii=False).encode()
        wire = ("POST /v1/audio/speech HTTP/1.1\r\nHost: 127.0.0.1:9945\r\nContent-Type: application/json\r\nContent-Length: " + str(len(body)) + "\r\nConnection: close\r\n\r\n").encode() + body
        for _ in range(8):
            connection = socket.create_connection(("127.0.0.1", 9945), timeout=5)
            connection.sendall(wire)
            peers.append(connection)
        queue_deadline = time.monotonic() + 5
        while time.monotonic() < queue_deadline and health().get("requests_active") != 8:
            time.sleep(0.1)
        report["acceptedQueueCount"] = health().get("requests_active")
        report["ninthRequestStatus"] = synthesize("这是第九条合成队列测试。")["status"]
        for connection in peers:
            connection.close()
        peers.clear()
        cancelled_at = time.monotonic()
        while time.monotonic() - cancelled_at < 15 and health().get("requests_active") != 0:
            time.sleep(0.2)
        report["queueReleasedAfterDisconnect"] = health().get("requests_active") == 0
        report["disconnectCleanupSeconds"] = round(time.monotonic() - cancelled_at, 3)
        with ThreadPoolExecutor(max_workers=2) as pool:
            report["concurrentChunks"] = list(pool.map(synthesize, ["先看第一项。", "再看第二项。"]))
        final = health()
        report["requestsActiveAfterTest"] = final["requests_active"]
        report["successfulSynthesisDelta"] = final["metrics"]["tts_requests"] - before["metrics"]["tts_requests"]
        report["network"] = final["network"]
        report["ok"] = (report["acceptedQueueCount"] == 8 and report["ninthRequestStatus"] == 429
                        and report["queueReleasedAfterDisconnect"] and final["requests_active"] == 0
                        and all(chunk.get("status") == 200 and chunk.get("wave_header") for chunk in report["concurrentChunks"])
                        and final["network"]["blocked_attempts"] == 0)
    except Exception as error:
        report["error_type"] = type(error).__name__
    finally:
        for connection in peers:
            connection.close()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
