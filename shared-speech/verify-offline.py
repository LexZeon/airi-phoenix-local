"""Exercise the real loopback audio API with outbound requests blocked."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import time
from urllib.request import Request, urlopen
import uuid
import wave

import importlib.util

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("airi_speech_server", ROOT / "speech-server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

BASE = "http://127.0.0.1:9942"
OUTPUT = ROOT / "verification"
OUTPUT.mkdir(exist_ok=True)


def api_json(path):
    with urlopen(BASE + path, timeout=10) as response:
        return json.load(response)


def transcribe(data, filename, mime):
    boundary = "airi-" + uuid.uuid4().hex
    parts = []
    for name, value in (("model", "sensevoice-local"), ("language", "zh")):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\nContent-Type: {mime}\r\n\r\n".encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    request = Request(BASE + "/v1/audio/transcriptions", data=b"".join(parts), headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Authorization": "Bearer local-offline"})
    started = time.perf_counter()
    with urlopen(request, timeout=120) as response:
        result = json.load(response)
    return {"text": result["text"], "seconds": round(time.perf_counter() - started, 3)}


def speak(text, audio_format):
    request = Request(BASE + "/v1/audio/speech", data=json.dumps({"model": "melo-tts-zh-en", "voice": "zh_default", "input": text, "response_format": audio_format, "speed": 1.0}, ensure_ascii=False).encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer local-offline"})
    with urlopen(request, timeout=120) as response:
        audio = response.read()
        result = {"bytes": len(audio), "content_type": response.headers.get("Content-Type"), "audio_seconds": response.headers.get("X-AIRI-Audio-Seconds"), "generation_seconds": response.headers.get("X-AIRI-Generation-Seconds"), "sha256": hashlib.sha256(audio).hexdigest()}
    (OUTPUT / ("chinese-offline." + audio_format)).write_bytes(audio)
    assert len(audio) > 5000
    return audio, result


if __name__ == "__main__":
    health = api_json("/health")
    assert health["ready"] and health["offline_network_guard"]["enabled"]
    source = Path(server.CONFIG["asr_directory"]) / "test_wavs" / "zh.wav"
    sample = source.read_bytes()
    wav_asr = transcribe(sample, "zh.wav", "audio/wav")
    assert "时间" in wav_asr["text"]
    browser_audio = subprocess.run([server.CONFIG["ffmpeg"], "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-c:a", "libopus", "-f", "webm", "pipe:1"], input=sample, stdout=subprocess.PIPE, check=True, creationflags=subprocess.CREATE_NO_WINDOW).stdout
    webm_asr = transcribe(browser_audio, "microphone.webm", "audio/webm")
    assert "时间" in webm_asr["text"]
    text = "你好，我是你的本地语音助手。断网以后也可以用中文和你聊天。"
    wav, wav_result = speak(text, "wav")
    with wave.open(io.BytesIO(wav)) as reader:
        assert reader.getnchannels() == 1 and reader.getnframes() > reader.getframerate()
    mp3, mp3_result = speak("你好，离线语音已经准备好了。", "mp3")
    roundtrip = transcribe(wav, "generated.wav", "audio/wav")
    assert "你好" in roundtrip["text"]
    result = {"external_network_requests_blocked": server.NETWORK_AUDIT, "service_health": api_json("/health"), "models": api_json("/v1/models"), "wav_asr": wav_asr, "webm_asr": webm_asr, "tts_input": text, "wav_tts": wav_result, "mp3_tts": mp3_result, "generated_speech_asr": roundtrip}
    (OUTPUT / "offline-verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, indent=2))
