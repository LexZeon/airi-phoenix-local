#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Loopback-only OpenAI-compatible Qwen3-TTS CustomVoice API."""

import argparse
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import select
import socket
import sys
import threading
import time
import wave


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--deps", action="append", default=[], type=Path)
    parser.add_argument("--styles", type=Path, default=Path(__file__).parent / "styles.json")
    parser.add_argument("--host", choices=["127.0.0.1"], default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9945)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")
    for directory in reversed(args.deps):
        sys.path.insert(0, str(directory.resolve()))
    from offline import install_offline_policy
    network = install_offline_policy()
    config = json.loads(args.styles.read_text(encoding="utf-8-sig"))
    state = {"service": "airi-phoenix-qwen-tts", "ready": False, "loading": True,
             "model": config["model_id"], "speaker": config["speaker"], "voices": list(config["voices"]),
             "network": network, "load_error_type": None, "requests_active": 0}
    engines = {}
    # AIRI may prefetch speech for several sentence chunks. Accept a bounded
    # queue, then let the engine's lock serialize GPU generation for every one.
    request_slot = threading.BoundedSemaphore(8)
    count_lock = threading.Lock()

    def load():
        try:
            from engine import TTSEngine
            engine = TTSEngine(args.model_dir, args.styles)
            engines["tts"] = engine
            state.update(ready=True, loading=False, load_seconds=round(engine.load_seconds, 3))
            print("Local Qwen3-TTS model ready.", file=sys.stderr, flush=True)
        except Exception as error:
            state.update(ready=False, loading=False, load_error_type=type(error).__name__)
            print("Local Qwen3-TTS load failed: " + type(error).__name__, file=sys.stderr, flush=True)

    class Handler(BaseHTTPRequestHandler):
        server_version = "PhoenixLocalVoice/0.1"

        def log_message(self, _format, *_args):
            return  # Never log request bodies, user text, or query strings.

        def send_bytes(self, status, data=b"", media_type="application/json", headers=None):
            self.send_response(status)
            self.send_header("Content-Type", media_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Authorization,Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET,HEAD,POST,OPTIONS")
            self.send_header("Cache-Control", "no-store")
            for key, value in (headers or {}).items():
                self.send_header(key, str(value))
            self.end_headers()
            if self.command != "HEAD":
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        def send_json(self, status, payload):
            self.send_bytes(status, json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"))

        def error(self, status, code, message):
            self.send_json(status, {"error": {"type": "invalid_request_error" if status < 500 else "server_error", "code": code, "message": message}})

        def do_OPTIONS(self):
            self.send_bytes(204)

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            endpoint = self.path.split("?", 1)[0]
            if endpoint == "/health":
                engine = engines.get("tts")
                self.send_json(200, {**state, "metrics": engine.metrics.copy() if engine else {},
                                     "audio": {"sample_rate": 24000, "channels": 1, "formats": ["wav", "pcm", "mp3", "flac"]},
                                     "mode": "batch-text-only", "cloning": False})
            elif endpoint == "/v1/models":
                self.send_json(200, {"object": "list", "data": [{"id": config["model_id"], "object": "model", "owned_by": "local", "name": "Qwen3-TTS Serena local"}]})
            elif endpoint == "/v1/audio/voices":
                voices = [{"id": alias, "voice_id": alias, "name": style["name"], "language": "zh", "languages": ["zh"], "object": "voice"} for alias, style in config["voices"].items()]
                self.send_json(200, {"object": "list", "data": voices, "voices": voices})
            else:
                self.error(404, "NOT_FOUND", "Unknown local endpoint")

        def do_POST(self):
            if self.path.split("?", 1)[0] != "/v1/audio/speech":
                self.error(404, "NOT_FOUND", "Unknown local endpoint")
                return
            if not state["ready"]:
                self.error(503, "MODEL_NOT_READY", "The local model is loading or unavailable; check /health")
                return
            if not request_slot.acquire(blocking=False):
                self.error(429, "VOICE_BUSY", "The local speech queue is full; retry after pending chunks finish")
                return
            with count_lock:
                state["requests_active"] += 1
            try:
                try:
                    self.connection.settimeout(15)
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 65536:
                        raise ValueError()
                    data = json.loads(self.rfile.read(length).decode("utf-8"))
                    if not isinstance(data, dict):
                        raise ValueError()
                except (ValueError, UnicodeError):
                    self.error(400, "INVALID_JSON", "Supply one JSON object of at most 64 KiB")
                    return
                if data.get("model", config["model_id"]) != config["model_id"]:
                    self.error(400, "UNKNOWN_MODEL", "Use the local model listed at /v1/models")
                    return
                audio_format = data.get("response_format", "mp3")
                if audio_format not in ("wav", "pcm", "mp3", "flac"):
                    self.error(400, "UNSUPPORTED_FORMAT", "Supported formats: wav, pcm, mp3, flac")
                    return
                began = time.monotonic()
                def client_cancelled():
                    try:
                        readable, _, _ = select.select([self.connection], [], [], 0)
                        return bool(readable and self.connection.recv(1, socket.MSG_PEEK) == b"")
                    except (OSError, ValueError):
                        return True
                try:
                    audio, metrics = engines["tts"].synthesize(data.get("input"), data.get("voice"), data.get("speed", 1.0),
                                                              cancelled=client_cancelled, queue_timeout=120, generation_timeout=120)
                except ValueError as error:
                    self.error(400, "INVALID_SPEECH_ARGUMENT", str(error))
                    return
                if audio_format == "pcm":
                    with wave.open(io.BytesIO(audio), "rb") as reader:
                        audio = reader.readframes(reader.getnframes())
                    media_type = "audio/pcm"
                elif audio_format in ("mp3", "flac"):
                    import soundfile as sf
                    samples, sample_rate = sf.read(io.BytesIO(audio), dtype="float32")
                    encoded = io.BytesIO()
                    sf.write(encoded, samples, sample_rate, format=audio_format.upper())
                    audio = encoded.getvalue()
                    media_type = "audio/mpeg" if audio_format == "mp3" else "audio/flac"
                else:
                    media_type = "audio/wav"
                self.send_bytes(200, audio, media_type, {"X-AIRI-Audio-Seconds": metrics["audio_seconds"],
                    "X-AIRI-Generation-Seconds": round(time.monotonic() - began, 4), "X-AIRI-RTF": metrics["rtf"],
                    "X-AIRI-Voice-Profile": metrics["profile"]})
            except ConnectionAbortedError:
                return
            except TimeoutError:
                self.error(504, "SPEECH_TIMEOUT", "Local speech exceeded its time limit; its queue slot was released. Try a shorter sentence.")
            except Exception as error:
                print("Local synthesis failed: " + type(error).__name__, file=sys.stderr, flush=True)
                self.error(500, "SYNTHESIS_FAILED", "Local synthesis failed; no input text was logged")
            finally:
                with count_lock:
                    state["requests_active"] -= 1
                request_slot.release()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    threading.Thread(target=load, daemon=True).start()
    print(f"Local voice API listening on loopback port {args.port}.", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
