"""Local OpenAI-compatible Chinese ASR and TTS for AIRI."""
import asyncio
import io
import ipaddress
import json
import math
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import threading
import time
import wave
from contextlib import asynccontextmanager

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8-sig"))
if platform.machine().upper() == "ARM64":
    sys.path.insert(0, str(ROOT / "native-packages"))
NETWORK_AUDIT = {"blocked_attempts": 0, "enabled": True}
_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex
_original_getaddrinfo = socket.getaddrinfo


def local_address(address):
    host = address[0] if isinstance(address, tuple) else address
    if host is None or host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        return False


def guard_address(address):
    if not local_address(address):
        NETWORK_AUDIT["blocked_attempts"] += 1
        raise PermissionError("This speech service only allows loopback network connections")


def guarded_connect(connection, address):
    guard_address(address)
    return _original_connect(connection, address)


def guarded_connect_ex(connection, address):
    guard_address(address)
    return _original_connect_ex(connection, address)


def guarded_getaddrinfo(host, *args, **kwargs):
    guard_address(host)
    return _original_getaddrinfo(host, *args, **kwargs)


socket.socket.connect = guarded_connect
socket.socket.connect_ex = guarded_connect_ex
socket.getaddrinfo = guarded_getaddrinfo
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"


def verify_offline_guard():
    try:
        socket.getaddrinfo("airi-offline.invalid", 443)
        raise RuntimeError("External DNS was not blocked")
    except PermissionError:
        pass
    with socket.socket() as probe:
        try:
            probe.connect(("203.0.113.1", 443))
            raise RuntimeError("External sockets were not blocked")
        except PermissionError:
            pass
    NETWORK_AUDIT["self_test_passed"] = True


verify_offline_guard()

import numpy as np
import sherpa_onnx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field
from scipy.signal import resample_poly

ASR_ID = "sensevoice-local"
TTS_ID = "melo-tts-zh-en"
VOICE_ID = "zh_default"
ASR_LOCK = threading.Lock()
TTS_LOCK = threading.Lock()
ENGINES = {}
METRICS = {"asr_requests": 0, "tts_requests": 0}


def load_models():
    asr_dir = Path(CONFIG["asr_directory"])
    tts_dir = ROOT / "models" / "melo-zh-en"
    ENGINES["asr"] = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(asr_dir / "model.int8.onnx"), tokens=str(asr_dir / "tokens.txt"),
        num_threads=CONFIG.get("asr_threads", 3), use_itn=True, provider="cpu",
    )
    tts_config = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=str(tts_dir / "model.int8.onnx"), lexicon=str(tts_dir / "lexicon.txt"),
                tokens=str(tts_dir / "tokens.txt"),
            ),
            num_threads=CONFIG.get("tts_threads", 3), provider="cpu", debug=False,
        ),
        rule_fsts=",".join(str(tts_dir / name) for name in ("date.fst", "number.fst", "phone.fst", "new_heteronym.fst")),
        max_num_sentences=1,
    )
    if not tts_config.validate():
        raise RuntimeError("Invalid local TTS model configuration")
    ENGINES["tts"] = sherpa_onnx.OfflineTts(tts_config)


@asynccontextmanager
async def lifespan(app):
    await asyncio.to_thread(load_models)
    yield
    ENGINES.clear()


app = FastAPI(title="AIRI Offline Speech", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], expose_headers=["X-AIRI-Audio-Seconds", "X-AIRI-Generation-Seconds"])


@app.get("/health")
def health():
    return {"service": "airi-offline-speech", "ready": len(ENGINES) == 2,
            "asr_model": ASR_ID, "tts_model": TTS_ID, "voice": VOICE_ID,
            "architecture": platform.machine(), "python": sys.executable,
            "sherpa_version": sherpa_onnx.__version__,
            "offline_network_guard": NETWORK_AUDIT, "metrics": METRICS,
            "sample_rate": ENGINES["tts"].sample_rate if "tts" in ENGINES else None}


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": name, "object": "model", "created": 0, "owned_by": "local"} for name in (ASR_ID, TTS_ID)]}


@app.get("/v1/audio/voices")
def voices():
    return {"voices": [{"id": VOICE_ID, "name": "Melo Chinese / English", "language": "zh-CN", "speaker_id": 0}]}


@app.api_route("/offline-assets/silero-vad/onnx/model.onnx", methods=["GET", "HEAD"])
def silero_vad_asset():
    path = ROOT.parent / "airi-offline-assets" / "silero-vad" / "onnx" / "model.onnx"
    if not path.is_file():
        raise HTTPException(503, "The local Silero VAD asset is missing")
    return FileResponse(path, media_type="application/octet-stream", headers={"Access-Control-Allow-Origin": "*"})


def run_ffmpeg(arguments, data):
    result = subprocess.run(
        [CONFIG["ffmpeg"], "-hide_banner", "-loglevel", "error", "-nostdin", *arguments],
        input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if result.returncode:
        raise HTTPException(400, "Audio conversion failed: " + result.stderr.decode("utf-8", errors="replace")[-500:])
    return result.stdout


@app.post("/v1/audio/transcriptions")
async def transcriptions(file: UploadFile = File(...), model: str = Form(ASR_ID), response_format: str = Form("json"), language: str = Form("zh")):
    if model not in (ASR_ID, "whisper-1"):
        raise HTTPException(400, "Use model sensevoice-local")
    data = await file.read(32 * 1024 * 1024 + 1)
    if len(data) > 32 * 1024 * 1024:
        raise HTTPException(413, "Audio must be smaller than 32 MiB")
    def transcribe():
        raw = run_ffmpeg(["-protocol_whitelist", "file,pipe,crypto,data", "-i", "pipe:0", "-f", "f32le", "-ac", "1", "-ar", "16000", "pipe:1"], data)
        samples = np.frombuffer(raw, dtype="<f4")
        if not samples.size:
            raise HTTPException(400, "Audio contains no samples")
        with ASR_LOCK:
            stream = ENGINES["asr"].create_stream()
            stream.accept_waveform(16000, samples)
            ENGINES["asr"].decode_stream(stream)
            text = stream.result.text
        METRICS["asr_requests"] += 1
        return text, samples.size / 16000
    text, duration = await asyncio.to_thread(transcribe)
    if response_format == "text":
        return PlainTextResponse(text)
    if response_format == "verbose_json":
        return {"task": "transcribe", "language": "chinese", "duration": duration, "text": text, "segments": []}
    return {"text": text}


class SpeechRequest(BaseModel):
    model: str = TTS_ID
    input: str = Field(min_length=1, max_length=5000)
    voice: str = VOICE_ID
    response_format: str = "mp3"
    speed: float = Field(default=1.0, ge=0.25, le=4.0)


@app.post("/v1/audio/speech")
def speech(request: SpeechRequest):
    if request.model not in (TTS_ID, "tts-1"):
        raise HTTPException(400, "Use model melo-tts-zh-en")
    if request.voice not in (VOICE_ID, "alloy", "0"):
        raise HTTPException(400, "Use voice zh_default")
    started = time.perf_counter()
    with TTS_LOCK:
        generated = ENGINES["tts"].generate(request.input, sid=0, speed=request.speed)
    samples = np.asarray(generated.samples, dtype=np.float32)
    sample_rate = generated.sample_rate
    if not samples.size:
        raise HTTPException(422, "The text produced no speech")
    output_format = request.response_format.lower()
    if output_format == "wav":
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(sample_rate)
            writer.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
        audio, media_type = buffer.getvalue(), "audio/wav"
    elif output_format == "pcm":
        divisor = math.gcd(sample_rate, 24000)
        samples = resample_poly(samples, 24000 // divisor, sample_rate // divisor)
        audio, media_type = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes(), "audio/pcm"
    else:
        encoders = {"mp3": ("libmp3lame", "mp3", "audio/mpeg"), "opus": ("libopus", "ogg", "audio/ogg"), "aac": ("aac", "adts", "audio/aac"), "flac": ("flac", "flac", "audio/flac")}
        if output_format not in encoders:
            raise HTTPException(400, "Supported formats: wav, mp3, pcm, opus, aac, flac")
        codec, container, media_type = encoders[output_format]
        audio = run_ffmpeg(["-f", "f32le", "-ar", str(sample_rate), "-ac", "1", "-i", "pipe:0", "-codec:a", codec, "-f", container, "pipe:1"], samples.astype("<f4").tobytes())
    METRICS["tts_requests"] += 1
    return Response(audio, media_type=media_type, headers={"X-AIRI-Audio-Seconds": str(round(len(generated.samples) / sample_rate, 3)), "X-AIRI-Generation-Seconds": str(round(time.perf_counter() - started, 3))})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=9942, log_level="info", access_log=False)
