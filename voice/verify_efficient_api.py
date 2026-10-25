#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify the opt-in alias and synthetic sentence splitting on an existing local API."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import statistics
import time
import urllib.parse
import urllib.request
import wave

TEXT = "先休息一下吧。我在这里，慢慢来就好。"
PARTS = ["先休息一下吧。", "我在这里，慢慢来就好。"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:9945")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--skip-split", action="store_true")
    args = parser.parse_args()
    endpoint = urllib.parse.urlsplit(args.url)
    if endpoint.scheme != "http" or endpoint.hostname not in ("127.0.0.1", "localhost", "::1") or endpoint.username or endpoint.password:
        parser.error("Use an existing loopback HTTP service only")
    base = args.url.rstrip("/")
    output = args.out.resolve()
    repo_root = Path(__file__).resolve().parents[1]
    if output == repo_root or repo_root in output.parents or (output / "report.json").exists():
        parser.error("Use a fresh private output directory outside the public repository")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def get(path):
        with opener.open(base + path, timeout=10) as response:
            return json.load(response)
    catalog = get("/v1/audio/voices")
    ids = {item["id"] for item in catalog["data"]}
    if not {"phoenix-soft", "phoenix-soft-efficient"} <= ids:
        parser.error("The optional alias is not loaded; do not restart the service automatically")
    output.mkdir(parents=True)
    report = {"ok": False, "synthetic_only": True, "text": TEXT, "default_changed": False,
              "model": "phoenix-qwen3-tts-local", "before": get("/health"), "runs": [], "split_runs": []}
    def persist():
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    def synthesize(voice, text, name):
        body = json.dumps({"model": report["model"], "input": text, "voice": voice,
                           "response_format": "wav", "speed": 1}).encode("utf-8")
        began = time.perf_counter()
        request = urllib.request.Request(base + "/v1/audio/speech", data=body, headers={"Content-Type": "application/json"})
        with opener.open(request, timeout=180) as response:
            first_byte = time.perf_counter() - began
            audio = response.read()
            headers = {key: response.headers.get(key) for key in
                       ("X-AIRI-Audio-Seconds", "X-AIRI-Generation-Seconds", "X-AIRI-RTF", "X-AIRI-Voice-Profile")}
        elapsed = time.perf_counter() - began
        expected = "predictor-hidden-off" if voice == "phoenix-soft-efficient" else "default"
        if headers["X-AIRI-Voice-Profile"] != expected:
            raise RuntimeError("The loaded service did not confirm the requested voice profile")
        with wave.open(io.BytesIO(audio), "rb") as reader:
            duration = reader.getnframes() / reader.getframerate()
            if reader.getnchannels() != 1 or reader.getframerate() != 24000 or duration <= 0:
                raise RuntimeError("Invalid local speech WAV")
        (output / name).write_bytes(audio)
        return {"voice": voice, "first_response_seconds": first_byte, "first_complete_wav_seconds": elapsed,
                "audio_seconds": duration, "rtf": elapsed / duration, "headers": headers,
                "audio_sha256": hashlib.sha256(audio).hexdigest(), "sample_file": name}
    persist()
    try:
        report["warmup"] = synthesize("phoenix-soft", TEXT, "warmup.wav")
        for index, voice in enumerate(("phoenix-soft", "phoenix-soft-efficient", "phoenix-soft-efficient", "phoenix-soft"), 1):
            report["runs"].append(synthesize(voice, TEXT, f"alias-{index}.wav"))
            persist()
        report["waveforms_bit_identical"] = len({row["audio_sha256"] for row in report["runs"]}) == 1
        report["summary"] = {voice: {"n": 2, "median_complete_wav_seconds": statistics.median(
            row["first_complete_wav_seconds"] for row in report["runs"] if row["voice"] == voice)}
            for voice in ("phoenix-soft", "phoenix-soft-efficient")}
        if not args.skip_split:
            for repeat in (1, 2):
                first = synthesize("phoenix-soft", PARTS[0], f"split-{repeat}-1.wav")
                second = synthesize("phoenix-soft", PARTS[1], f"split-{repeat}-2.wav")
                gap = max(0.0, second["first_complete_wav_seconds"] - first["audio_seconds"])
                report["split_runs"].append({"parts": [first, second], "first_playable_seconds": first["first_complete_wav_seconds"],
                    "total_generation_seconds": first["first_complete_wav_seconds"] + second["first_complete_wav_seconds"],
                    "total_audio_seconds": first["audio_seconds"] + second["audio_seconds"],
                    "virtual_gap_seconds": gap,
                    "virtual_playback_finish_seconds": first["first_complete_wav_seconds"] + first["audio_seconds"] + gap + second["audio_seconds"]})
                persist()
            report["split_scope"] = "Sequential API prefetch simulation: second generation starts when the first WAV becomes playable. Gap is calculated, no audio was played. AIRI already chunks text; this is not proof of a new integrated playback speedup. Splitting can alter prosody and pauses."
        report["after"] = get("/health")
        report["ok"] = report["waveforms_bit_identical"]
    except Exception as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)[:300]}
    finally:
        persist()
    print(json.dumps({"ok": report["ok"], "report": str(output / "report.json"),
                      "waveforms_bit_identical": report.get("waveforms_bit_identical"),
                      "summary": report.get("summary"), "split_runs": report["split_runs"]}, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
