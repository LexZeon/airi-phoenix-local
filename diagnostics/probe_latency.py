#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Explicit loopback-only synthetic HTTP stage timings. No microphone or app input."""
import argparse
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import secrets
import statistics
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT/"voice/samples/phoenix-soft.wav"
SAMPLE_SHA256 = "845dbba822164162816d65dd58a4a7cfe2edfa1e41c8e48d6a979a2cd7fde6ef"
SYNTHETIC_TEXT = "这是固定的本机合成测试。请只回答：今天也请慢慢来。"
TTS_TEXT = "先休息一下吧。我在这里，慢慢来就好。"
TTS_SEGMENTS = [TTS_TEXT, "今天也辛苦了。我们先把眼前的一件事慢慢做好。", "收到。我会先整理重点，再清楚地告诉你下一步。"]
MAX_RESPONSE = 32*1024*1024


class ProbeError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ProbeError("REDIRECT_REFUSED")


def local_endpoint(value):
    parsed = urllib.parse.urlsplit(value)
    host = "127.0.0.1" if parsed.hostname == "localhost" else parsed.hostname
    try:
        valid = ipaddress.ip_address(host).is_loopback
        port = parsed.port or 80
    except (ValueError, TypeError):
        valid = False
        port = 0
    if (not valid or parsed.scheme != "http" or parsed.username or parsed.password
            or parsed.query or parsed.fragment or not 1 <= port <= 65535
            or ".." in parsed.path or not re.fullmatch(r"/[A-Za-z0-9_./-]*", parsed.path)):
        raise argparse.ArgumentTypeError("Use an explicit http literal-loopback endpoint without credentials/query/fragment")
    host = "["+host+"]" if ":" in host else host
    return urllib.parse.urlunsplit(("http", f"{host}:{port}", parsed.path, "", ""))


def milliseconds(start):
    return round((time.perf_counter()-start)*1000, 3)


def wav_info(data):
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ProbeError("NOT_WAV")
    position, fmt, audio_bytes = 12, None, 0
    while position+8 <= len(data):
        name, size = struct.unpack_from("<4sI", data, position)
        begin, end = position+8, position+8+size
        if end > len(data):
            raise ProbeError("WAV_CHUNK_TRUNCATED")
        if name == b"fmt " and size >= 16:
            fmt = struct.unpack_from("<HHIIHH", data, begin)
        elif name == b"data":
            audio_bytes += size
        position = end+(size & 1)
    if not fmt:
        raise ProbeError("WAV_FORMAT_MISSING")
    code, channels, rate, _byte_rate, align, bits = fmt
    if code not in (1, 3, 0xfffe) or not 1 <= channels <= 8 or not 8000 <= rate <= 192000 or not align or audio_bytes % align:
        raise ProbeError("WAV_FORMAT_UNSUPPORTED")
    frames = audio_bytes//align
    if not frames:
        raise ProbeError("WAV_EMPTY_AUDIO")
    return {"sample_rate": rate, "channels": channels, "bits_per_sample": bits,
        "frames": frames, "audio_data_bytes": audio_bytes, "wav_audio_seconds": round(frames/rate, 6)}


def read_bounded(response):
    data = response.read(MAX_RESPONSE+1)
    if len(data) > MAX_RESPONSE:
        raise ProbeError("RESPONSE_TOO_LARGE")
    return data


def request_body(opener, url, body, media_type, headers, timeout):
    request = urllib.request.Request(url, body, {**headers, "Content-Type": media_type}, method="POST")
    start = time.perf_counter()
    with opener.open(request, timeout=timeout) as response:
        headers_ms = milliseconds(start)
        first = response.read(1)
        first_byte_ms = milliseconds(start) if first else None
        data = first+read_bounded(response)
        if not data or len(data) > MAX_RESPONSE:
            raise ProbeError("EMPTY_OR_LARGE_RESPONSE")
        return data, {"response_headers_ms": headers_ms, "first_body_byte_ms": first_byte_ms,
            "total_ms": milliseconds(start), "response_bytes": len(data)}


def asr_probe(opener, args, headers, audio):
    boundary = "synthetic-"+secrets.token_hex(12)
    parts = []
    for name, value in (("model", args.asr_model), ("language", "zh"), ("response_format", "json")):
        parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n").encode())
    parts.extend([(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"synthetic.wav\"\r\nContent-Type: audio/wav\r\n\r\n").encode(), audio, (f"\r\n--{boundary}--\r\n").encode()])
    data, timing = request_body(opener, args.asr_url, b"".join(parts), "multipart/form-data; boundary="+boundary, headers, args.timeout)
    payload = json.loads(data)
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ProbeError("ASR_EMPTY_TRANSCRIPT")
    return {**timing, "transcript_characters": len(text), "transcript_saved": False,
        "audio": wav_info(audio), "microphone_endpointing_measured": False}


def llm_probe(opener, args, headers):
    payload = {"model": args.llm_model, "messages": [{"role": "user", "content": SYNTHETIC_TEXT}],
        "stream": True, "max_tokens": args.max_tokens, "temperature": 0.2, "stream_options": {"include_usage": True}}
    request = urllib.request.Request(args.llm_url, json.dumps(payload).encode(), {**headers, "Content-Type": "application/json"}, method="POST")
    start = time.perf_counter()
    first_token = first_visible = first_event = None
    characters = reasoning_characters = events = received = 0
    usage = {}
    with opener.open(request, timeout=args.timeout) as response:
        headers_ms = milliseconds(start)
        if "text/event-stream" not in response.headers.get("Content-Type", "").lower():
            raise ProbeError("LLM_NON_STREAMING_RESPONSE")
        for raw in response:
            received += len(raw)
            if received > MAX_RESPONSE:
                raise ProbeError("RESPONSE_TOO_LARGE")
            line = raw.strip()
            if not line.startswith(b"data:"):
                continue
            item = line[5:].strip()
            if item == b"[DONE]":
                break
            if not item:
                continue
            if first_event is None:
                first_event = milliseconds(start)
            event = json.loads(item)
            if event.get("error"):
                raise ProbeError("LLM_SERVER_ERROR")
            events += 1
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = (event.get("usage") or {}).get(key)
                if isinstance(value, int):
                    usage[key] = value
            for choice in event.get("choices", []):
                delta = choice.get("delta") or {}
                content = delta.get("content") or ""
                reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
                if not isinstance(content, str) or not isinstance(reasoning, str):
                    raise ProbeError("LLM_DELTA_FORMAT_UNSUPPORTED")
                if (content or reasoning) and first_token is None:
                    first_token = milliseconds(start)
                if content.strip() and first_visible is None:
                    first_visible = milliseconds(start)
                characters += len(content)
                reasoning_characters += len(reasoning)
    if first_token is None or not characters:
        raise ProbeError("LLM_NO_VISIBLE_COMPLETION")
    return {"response_headers_ms": headers_ms, "first_sse_event_ms": first_event,
        "first_token_ms": first_token, "first_visible_text_ms": first_visible,
        "total_ms": milliseconds(start), "content_characters": characters,
        "reasoning_characters": reasoning_characters, "sse_events": events,
        "usage": usage, "reply_text_saved": False}


def tts_single(opener, args, headers, text):
    payload = {"model": args.tts_model, "voice": args.tts_voice, "input": text,
        "response_format": "wav", "speed": 1.0}
    data, timing = request_body(opener, args.tts_url, json.dumps(payload).encode(), "application/json", headers, args.timeout)
    audio = wav_info(data)
    return {**timing, **audio, "real_time_factor": round(timing["total_ms"]/1000/audio["wav_audio_seconds"], 6),
        "audio_saved": False, "physical_playback_measured": False}


def tts_probe(opener, args, headers):
    start = time.perf_counter()
    segments, virtual_end, gaps = [], None, []
    for index in range(args.tts_sequence):
        metrics = tts_single(opener, args, headers, TTS_SEGMENTS[index % len(TTS_SEGMENTS)])
        ready_ms = milliseconds(start)
        metrics.update(segment=index+1, complete_wav_ready_from_sequence_start_ms=ready_ms)
        if virtual_end is not None:
            gaps.append(round(max(0, ready_ms-virtual_end), 3))
        virtual_end = max(ready_ms, virtual_end or ready_ms)+metrics["wav_audio_seconds"]*1000
        segments.append(metrics)
    total_ms = milliseconds(start)
    duration = sum(segment["wav_audio_seconds"] for segment in segments)
    later_audio = sum(segment["wav_audio_seconds"] for segment in segments[1:])
    later_generation = sum(segment["total_ms"] for segment in segments[1:])/1000
    return {"first_body_byte_ms": segments[0]["first_body_byte_ms"],
        "api_first_complete_playable_wav_ms": segments[0]["complete_wav_ready_from_sequence_start_ms"],
        "physical_ttfa_ms": None, "total_ms": total_ms,
        "response_bytes": sum(segment["response_bytes"] for segment in segments),
        "wav_audio_seconds": round(duration, 6), "real_time_factor": round(total_ms/1000/duration, 6),
        "steady_state_generation_rtf": round(later_generation/later_audio, 6) if later_audio else None,
        "virtual_playback_gaps_ms": gaps, "virtual_playback_total_gap_ms": round(sum(gaps), 3),
        "sequence_mode": "Sequential HTTP generation with next request starting after previous full WAV; virtual playback begins at first complete WAV",
        "physical_continuous_playback_measured": False, "audio_saved": False, "segments": segments}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["all", "asr", "llm", "tts"], default="all")
    for name in ("asr", "llm", "tts"):
        parser.add_argument("--"+name+"-url", type=local_endpoint)
        parser.add_argument("--"+name+"-model")
    parser.add_argument("--tts-voice")
    parser.add_argument("--synthetic-audio", type=Path, help="Explicit replacement synthetic WAV only; default is the bundled original Serena test clip")
    parser.add_argument("--api-key-env", help="Optional process environment variable containing a local-service key; never printed")
    parser.add_argument("--repeat", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--tts-sequence", type=int, choices=range(1, 6), default=1, help="Fixed synthetic segments for generation-rate and virtual-playback-gap analysis; no actual playback")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--out", type=Path, help="Optional summary JSON; no transcripts, replies or generated audio")
    args = parser.parse_args()
    selected = ["asr", "llm", "tts"] if args.mode == "all" else [args.mode]
    if not 1 <= args.timeout <= 300:
        parser.error("timeout must be 1 to 300 seconds")
    if not 1 <= args.max_tokens <= 2048:
        parser.error("max-tokens must be 1 to 2048")
    suffixes = {"asr": "/audio/transcriptions", "llm": "/chat/completions", "tts": "/audio/speech"}
    for stage in selected:
        url, model = getattr(args, stage+"_url"), getattr(args, stage+"_model")
        if not url or not model or not url.endswith(suffixes[stage]):
            parser.error(f"{stage} needs explicit URL ending in {suffixes[stage]} and a model ID")
        if any(ord(c) < 32 for c in model):
            parser.error("model IDs cannot contain control characters")
    if "tts" in selected and not args.tts_voice:
        parser.error("TTS needs an explicit --tts-voice")
    headers = {"Accept": "application/json, audio/wav, text/event-stream", "User-Agent": "airi-character-forge-synthetic-probe/0.1"}
    if args.api_key_env:
        import os
        key = os.environ.get(args.api_key_env)
        if not key or any(ord(c) < 32 for c in key):
            parser.error("the selected key environment variable is missing or invalid")
        headers["Authorization"] = "Bearer "+key
    audio = None
    if "asr" in selected:
        try:
            audio = (args.synthetic_audio or SAMPLE).read_bytes()
            wav_info(audio)
        except (OSError, ProbeError):
            parser.error("Synthetic WAV is missing or invalid; no audio/path details are written to a report")
        if len(audio) > MAX_RESPONSE or (not args.synthetic_audio and hashlib.sha256(audio).hexdigest() != SAMPLE_SHA256):
            parser.error("default synthetic sample changed, or explicit audio is too large")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    report = {"tool": "synthetic-loopback-http-stage-probe", "version": "0.1.0",
        "testedAt": datetime.now(timezone.utc).isoformat(), "syntheticOnly": True,
        "workflow": "Isolated HTTP stages; LLM output is not passed to TTS; their sum is not real conversation latency",
        "rawInputsOrOutputsSaved": False, "microphoneOrScreenUsed": False,
        "configurationChanged": False, "onlineCandidates": "UNMEASURED by this loopback-only tool; no credentials or online API calls are inferred",
        "automaticWarmup": False, "requests": [], "summaries": {},
        "limits": ["HTTP ASR excludes microphone endpointing/VAD", "LLM TTFT is the first parsed nonempty content/reasoning delta; visible text is recorded separately", "TTS first byte does not imply streaming generation", "WAV duration counts valid sample frames, including silence", "No sound-card/acoustic playback measurement", "Cold load/queue/contention can affect each run"]}
    for run in range(1, args.repeat+1):
        for stage in selected:
            record = {"stage": stage, "run": run}
            start = time.perf_counter()
            try:
                metrics = asr_probe(opener, args, headers, audio) if stage == "asr" else llm_probe(opener, args, headers) if stage == "llm" else tts_probe(opener, args, headers)
                record.update(ok=True, metrics=metrics)
            except Exception as error:
                code = f"HTTP_{error.code}" if isinstance(error, urllib.error.HTTPError) else str(error) if isinstance(error, ProbeError) else type(error).__name__
                record.update(ok=False, code=code if re.fullmatch(r"[A-Za-z0-9_-]{1,80}", code) else "PROBE_FAILED", failed_elapsed_ms=milliseconds(start))
            report["requests"].append(record)
    for stage in selected:
        successes = [entry["metrics"] for entry in report["requests"] if entry["stage"] == stage and entry["ok"]]
        summary = {"successful_requests": len(successes), "requested_runs": args.repeat}
        for name in ("total_ms", "first_body_byte_ms", "api_first_complete_playable_wav_ms", "first_token_ms", "first_visible_text_ms", "wav_audio_seconds", "real_time_factor", "steady_state_generation_rtf", "virtual_playback_total_gap_ms"):
            values = [entry[name] for entry in successes if isinstance(entry.get(name), (int, float))]
            if values:
                summary[name] = {"min": min(values), "median": round(statistics.median(values), 6), "max": max(values)}
        report["summaries"][stage] = summary
    report["ok"] = all(entry["ok"] for entry in report["requests"])
    text = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)+"\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
