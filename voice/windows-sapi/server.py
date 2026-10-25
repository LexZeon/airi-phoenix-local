#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Windows Huihui SAPI5, loopback OpenAI-compatible WAV synthesis. No playback."""
import argparse
import base64
import dataclasses
import hmac
import io
import json
import math
import os
from pathlib import Path
import queue
import select
import socket
import subprocess
import threading
import time
import uuid
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from token_store import ensure_token

ROOT = Path(__file__).resolve().parent
MODEL = "windows-sapi-local"
VOICE = "huihui"
MAX_BODY = 32768
MAX_TEXT = 2000
MAX_WAV = 16 * 1024 * 1024 + 44
QUEUE_CAPACITY = 8  # Includes the one active request.


class SpeechFailure(Exception):
    def __init__(self, code, status=500):
        self.code, self.status = code, status


class Cancelled(SpeechFailure):
    def __init__(self):
        super().__init__("REQUEST_CANCELLED", 499)


def atomic_json(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=True), encoding="utf-8")
    os.replace(temporary, path)


class SapiWorker:
    def __init__(self, powershell, launch_id):
        self.powershell, self.launch_id = powershell, launch_id
        self.process = None
        self.lines = None
        self.identity = None

    def start(self):
        self.close()
        argv = [str(self.powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", str(ROOT / "worker.ps1"), "-OwnerLaunchId", self.launch_id]
        self.process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        text=True, encoding="utf-8", errors="strict", bufsize=1,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        process = self.process
        self.lines = queue.Queue(maxsize=4)
        lines = self.lines

        def read_stdout():
            try:
                while True:
                    line = process.stdout.readline((MAX_WAV * 4 // 3) + 8192)
                    if not line:
                        break
                    if not line.endswith("\n"):
                        raise ValueError("WORKER_PROTOCOL")
                    lines.put_nowait(json.loads(line))
            except Exception:
                pass
            finally:
                try:
                    lines.put_nowait({"ok": False, "code": "WORKER_EXITED"})
                except queue.Full:
                    pass

        threading.Thread(target=read_stdout, daemon=True).start()
        try:
            hello = self.lines.get(timeout=20)
            if not hello.get("ok") or hello.get("event") != "ready":
                raise SpeechFailure("VOICE_UNAVAILABLE" if hello.get("code") == "VOICE_UNAVAILABLE" else "WORKER_START_FAILED", 503)
            identity = hello.get("identity", {})
            if identity.get("pid") != process.pid or identity.get("parentPid") != os.getpid() or identity.get("launchId") != self.launch_id:
                raise SpeechFailure("WORKER_IDENTITY_FAILED", 503)
            self.identity = identity
            atomic_json(ROOT / "worker-state.json", {"owner": "airi-sapi-9947", "schemaVersion": 1,
                        "launchId": self.launch_id, "serverPid": os.getpid(), "worker": identity})
        except queue.Empty:
            self.close()
            raise SpeechFailure("WORKER_START_TIMEOUT", 503)
        except Exception:
            self.close()
            raise

    def synthesize(self, text, rate, cancelled):
        request_id = uuid.uuid4().hex
        try:
            self.process.stdin.write(json.dumps({"request_id": request_id, "input": text, "rate": rate}, ensure_ascii=True) + "\n")
            self.process.stdin.flush()
        except (OSError, AttributeError):
            self.close()
            raise SpeechFailure("WORKER_IO_FAILED")
        deadline = time.monotonic() + 30
        while True:
            if cancelled():
                self.close()
                raise Cancelled()
            if time.monotonic() >= deadline:
                self.close()
                raise SpeechFailure("SYNTHESIS_TIMEOUT", 504)
            try:
                result = self.lines.get(timeout=.025)
            except queue.Empty:
                continue
            if not result.get("ok") or result.get("request_id") != request_id:
                self.close()
                raise SpeechFailure("SYNTHESIS_FAILED")
            try:
                audio = base64.b64decode(result["wav_base64"], validate=True)
                if not 44 < len(audio) <= MAX_WAV:
                    raise ValueError()
                with wave.open(io.BytesIO(audio), "rb") as reader:
                    if (reader.getframerate(), reader.getnchannels(), reader.getsampwidth(), reader.getcomptype()) != (24000, 1, 2, "NONE"):
                        raise ValueError()
                    frames = reader.getnframes()
                    if not frames or len(reader.readframes(frames)) != frames * 2:
                        raise ValueError()
                seconds = frames / 24000
                generation = float(result["generation_seconds"])
                if not math.isfinite(generation) or generation < 0:
                    raise ValueError()
                return audio, seconds, generation
            except (KeyError, ValueError, TypeError, wave.Error):
                self.close()
                raise SpeechFailure("INVALID_WORKER_WAV")

    def close(self):
        process, self.process = self.process, None
        self.identity = None
        if process:
            if process.poll() is None:
                process.terminate()  # Exact Popen handle created by this server, never a guessed PID.
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            for stream in (process.stdin, process.stdout):
                if stream:
                    try:
                        stream.close()
                    except OSError:
                        pass


@dataclasses.dataclass
class Job:
    text: str
    rate: int
    created: float = dataclasses.field(default_factory=time.monotonic)
    cancelled: threading.Event = dataclasses.field(default_factory=threading.Event)
    done: threading.Event = dataclasses.field(default_factory=threading.Event)
    result: object = None
    error: object = None


class Broker:
    def __init__(self, powershell, launch_id):
        self.worker = SapiWorker(powershell, launch_id)
        self.jobs = queue.Queue(maxsize=QUEUE_CAPACITY)
        self.slots = threading.BoundedSemaphore(QUEUE_CAPACITY)
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.state = {"ready": False, "loading": True, "error_code": None, "requests_active": 0, "requests_queued": 0}
        self.metrics = {"tts_requests": 0, "tts_completed": 0, "tts_failures": 0, "tts_cancelled": 0,
                        "queue_rejections": 0, "worker_restarts": 0, "last_generation_seconds": None, "last_audio_seconds": None}
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def ready_worker(self):
        with self.lock:
            self.state.update(ready=False, loading=True, error_code=None)
        try:
            self.worker.start()
        except Exception as exc:
            with self.lock:
                self.state.update(ready=False, loading=False, error_code=exc.code if isinstance(exc, SpeechFailure) else "WORKER_START_FAILED")
            return False
        with self.lock:
            self.state.update(ready=True, loading=False, error_code=None)
        return True

    def submit(self, text, rate):
        with self.lock:
            if not self.state["ready"]:
                raise SpeechFailure("SERVICE_NOT_READY", 503)
        if not self.slots.acquire(blocking=False):
            with self.lock:
                self.metrics["queue_rejections"] += 1
            raise SpeechFailure("VOICE_BUSY", 429)
        job = Job(text, rate)
        with self.lock:
            self.state["requests_queued"] += 1
        self.jobs.put_nowait(job)
        return job

    def run(self):
        self.ready_worker()
        while not self.stopping.is_set():
            try:
                job = self.jobs.get(timeout=.1)
            except queue.Empty:
                continue
            with self.lock:
                self.state["requests_queued"] -= 1
                self.state["requests_active"] += 1
            try:
                if job.cancelled.is_set():
                    raise Cancelled()
                if time.monotonic() - job.created > 60:
                    raise SpeechFailure("QUEUE_TIMEOUT", 504)
                if self.worker.process is None and not self.ready_worker():
                    raise SpeechFailure("SERVICE_NOT_READY", 503)
                began = time.monotonic()
                with self.lock:
                    self.metrics["tts_requests"] += 1
                audio, seconds, generation = self.worker.synthesize(job.text, job.rate, job.cancelled.is_set)
                job.result = (audio, seconds, generation, began - job.created, time.monotonic() - job.created)
                with self.lock:
                    self.metrics.update(tts_completed=self.metrics["tts_completed"] + 1,
                                        last_generation_seconds=round(generation, 6), last_audio_seconds=seconds)
            except SpeechFailure as exc:
                job.error = exc
                with self.lock:
                    self.metrics["tts_cancelled" if isinstance(exc, Cancelled) else "tts_failures"] += 1
            except Exception:
                job.error = SpeechFailure("SYNTHESIS_FAILED")
                self.worker.close()
                with self.lock:
                    self.metrics["tts_failures"] += 1
            finally:
                job.text = ""
                with self.lock:
                    self.state["requests_active"] -= 1
                job.done.set()
                self.slots.release()
                self.jobs.task_done()
            if self.worker.process is None and not self.stopping.is_set():
                with self.lock:
                    self.metrics["worker_restarts"] += 1
                self.ready_worker()
        self.worker.close()

    def snapshot(self):
        with self.lock:
            return {**self.state, "metrics": self.metrics.copy(), "worker_pid": self.worker.identity.get("pid") if self.worker.identity else None}

    def close(self):
        self.stopping.set()
        self.worker.close()


def make_handler(broker, token, launch_id, port):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    origins = {"null", f"http://127.0.0.1:{port}", f"http://localhost:{port}",
               "http://127.0.0.1:9944", "http://localhost:9944"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "AiriWindowsSapi/1.0"
        protocol_version = "HTTP/1.0"

        def log_message(self, *_args):
            pass  # No text, audio, auth header, request path, or query logging.

        def gate(self):
            host = self.headers.get_all("Host", [])
            origin = self.headers.get_all("Origin", [])
            if len(host) != 1 or host[0].lower() not in hosts:
                self.error(403, "HOST_DENIED")
                return False
            if len(origin) > 1 or (origin and origin[0] not in origins):
                self.error(403, "ORIGIN_DENIED")
                return False
            return True

        def send_data(self, status, body=b"", content_type="application/json", headers=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Vary", "Origin")
            origin = self.headers.get("Origin")
            if origin in origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS")
                self.send_header("Access-Control-Expose-Headers", "X-AIRI-Audio-Seconds, X-AIRI-Generation-Seconds, X-AIRI-Queue-Seconds, X-AIRI-Total-Seconds")
            for key, value in (headers or {}).items():
                self.send_header(key, str(value))
            self.end_headers()
            if self.command != "HEAD":
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

        def json(self, status, value):
            self.send_data(status, json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))

        def error(self, status, code):
            self.json(status, {"error": {"type": "local_speech_error", "code": code, "message": code}})

        def do_OPTIONS(self):
            if not self.gate():
                return
            method = self.headers.get("Access-Control-Request-Method", "POST")
            headers = {x.strip().lower() for x in self.headers.get("Access-Control-Request-Headers", "").split(",") if x.strip()}
            if method not in {"GET", "HEAD", "POST"} or not headers.issubset({"authorization", "content-type"}):
                self.error(403, "PREFLIGHT_DENIED")
                return
            self.send_data(204)

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            if not self.gate():
                return
            if self.path == "/health":
                self.json(200, {"service": "airi-windows-sapi", "instance_id": launch_id, "pid": os.getpid(),
                               "model": MODEL, "voice": VOICE, "auth_required": True, **broker.snapshot(),
                               "audio": {"sample_rate": 24000, "channels": 1, "bits": 16, "formats": ["wav"]},
                               "offline": True, "playback": False, "cloning": False, "style_instructions": False,
                               "serena_voice_preserved": False, "queue_capacity": QUEUE_CAPACITY})
            elif self.path == "/v1/models":
                self.json(200, {"object": "list", "data": [{"id": MODEL, "object": "model", "owned_by": "windows-local", "name": "Windows SAPI Huihui"}]})
            elif self.path == "/v1/audio/voices":
                voices = [{"id": VOICE, "voice_id": VOICE, "name": "Microsoft Huihui Desktop", "object": "voice", "language": "zh", "languages": ["zh-CN"]}]
                self.json(200, {"object": "list", "data": voices, "voices": voices})
            else:
                self.error(404, "NOT_FOUND")

        def do_POST(self):
            if not self.gate():
                return
            if self.path != "/v1/audio/speech":
                self.error(404, "NOT_FOUND")
                return
            auth = self.headers.get_all("Authorization", [])
            if len(auth) != 1 or not hmac.compare_digest(auth[0].encode("utf-8"), ("Bearer " + token).encode("ascii")):
                self.error(401, "AUTH_REQUIRED")
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                self.error(415, "JSON_REQUIRED")
                return
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or self.headers.get("Transfer-Encoding"):
                self.error(400, "INVALID_LENGTH")
                return
            try:
                size = int(lengths[0])
                if not 0 < size <= MAX_BODY:
                    raise ValueError()
                self.connection.settimeout(10)
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError()
                data = json.loads(raw.decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError()
            except (ValueError, UnicodeError, OSError):
                self.error(400, "INVALID_JSON")
                return
            if data.get("model", MODEL) != MODEL:
                self.error(400, "UNKNOWN_MODEL")
                return
            if data.get("voice", VOICE) != VOICE:
                self.error(400, "UNKNOWN_VOICE")
                return
            if data.get("response_format", "wav") != "wav":
                self.error(400, "WAV_ONLY")
                return
            if data.get("stream") or data.get("instructions"):
                self.error(400, "UNSUPPORTED_OPTION")
                return
            text = data.get("input")
            speed = data.get("speed", 1)
            if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT or any(ord(c) < 32 and c not in "\n\r\t" for c in text):
                self.error(400, "INVALID_INPUT")
                return
            if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not math.isfinite(speed) or not .25 <= speed <= 4:
                self.error(400, "INVALID_SPEED")
                return
            # SAPI is an integer-rate system voice; rate is approximate and discrete.
            rate = max(-10, min(10, round(math.log2(speed) * 5)))
            try:
                job = broker.submit(text, rate)
            except SpeechFailure as exc:
                self.error(exc.status, exc.code)
                return
            while not job.done.wait(.025):
                try:
                    readable, _, _ = select.select([self.connection], [], [], 0)
                    if readable and self.connection.recv(1, socket.MSG_PEEK) == b"":
                        job.cancelled.set()
                        return
                except OSError:
                    job.cancelled.set()
                    return
                if time.monotonic() - job.created > 95:
                    job.cancelled.set()
                    self.error(504, "REQUEST_TIMEOUT")
                    return
            if job.error:
                self.error(job.error.status, job.error.code)
                return
            audio, seconds, generation, queued, total = job.result
            self.send_data(200, audio, "audio/wav", {"X-AIRI-Audio-Seconds": round(seconds, 6),
                           "X-AIRI-Generation-Seconds": round(generation, 6), "X-AIRI-Queue-Seconds": round(queued, 6),
                           "X-AIRI-Total-Seconds": round(total, 6)})
            job.result = None

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=["127.0.0.1"], default="127.0.0.1")
    parser.add_argument("--port", choices=[9947], type=int, default=9947)
    parser.add_argument("--launch-id", required=True)
    args = parser.parse_args()
    if len(args.launch_id) != 32 or any(c not in "0123456789abcdef" for c in args.launch_id):
        parser.error("Invalid launch identity")
    if os.name != "nt":
        parser.error("Windows required")
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    if not powershell.is_file():
        parser.error("Windows PowerShell not installed")
    token = ensure_token(ROOT / "api-token.txt")
    broker = Broker(powershell, args.launch_id)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(broker, token, args.launch_id, args.port))
    server.daemon_threads = True
    try:
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        broker.close()


if __name__ == "__main__":
    main()
