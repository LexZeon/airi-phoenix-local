# SPDX-License-Identifier: MIT
"""Aliyun's documented HTTP SSE speech protocols, with separate audio timings.

The current AIRI compatible speech provider waits for a complete WAV. Upstream
firstAudioMs is therefore not a measurement of sound played by AIRI.
"""
from __future__ import annotations

import base64
import binascii
import importlib.util
import io
import json
import math
import socket
import struct
import threading
import time
from pathlib import Path
import urllib.error
import urllib.request
import wave

ROOT = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('airi_aliyun_private_configuration_engine', ROOT / 'aliyun_config.py')
config_store = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(config_store)
SAMPLE_RATE = 24000
MAX_AUDIO = 16 * 1024 * 1024
MAX_EVENT = 2 * 1024 * 1024
MAX_SECONDS = 90
TEST_TEXT = '先休息一下吧。我在这里，慢慢来就好。'
STYLE_INSTRUCTIONS = {
    'gentle': '温柔、略带倦意，语速稍慢，吐字清楚。句子之间停顿自然紧凑，不刻意拖长。',
    'drowsy': '语气温柔困倦，轻声说话，节奏稍慢，保持清楚自然。',
    'focused': '温柔但利落清楚，工作时干练，节奏自然，避免拖长停顿。',
    'neutral': '清楚自然地说中文，停顿简洁。',
}


class EngineError(RuntimeError):
    def __init__(self, code, message, status=502):
        self.code, self.status = code, status
        super().__init__(message)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise EngineError('UPSTREAM_REDIRECT_DENIED', '阿里语音返回了意外跳转，未跟随。')


def _public_error(code):
    upper = str(code).upper()
    if any(item in upper for item in ('INVALIDAPIKEY', 'INVALID_API_KEY', 'UNAUTHORIZED', 'AUTHENTICATION', 'API_KEY')):
        return EngineError('ALIYUN_AUTH_FAILED', '阿里云密钥未通过验证，请核对密钥和所选地域。', 401)
    if any(item in upper for item in ('INSUFFICIENT', 'QUOTA', 'ARREARAGE', 'BALANCE', 'PAYMENT')):
        return EngineError('ALIYUN_QUOTA_UNAVAILABLE', '阿里云额度或余额不可用，请在百炼控制台检查。', 402)
    if any(item in upper for item in ('THROTTL', 'RATE_LIMIT', 'RATE LIMIT', 'LIMITREQUEST')):
        return EngineError('ALIYUN_RATE_LIMIT', '阿里语音请求过于频繁，请稍后重试。', 429)
    if any(item in upper for item in ('MODEL', 'UNSUPPORTED', 'INVALIDPARAMETER', 'INVALID_PARAMETER')):
        return EngineError('ALIYUN_MODEL_OR_PARAMETER', '当前地域、模型或音色未被服务接受，请检查配置。', 400)
    return EngineError('ALIYUN_REQUEST_FAILED', '阿里语音请求未完成，请检查账号权限、地域和配置。')


def _error_object(value):
    if not isinstance(value, dict):
        return None
    if value.get('code') and str(value['code']).lower() not in ('200', 'ok', 'success'):
        return _public_error(value['code'])
    if value.get('error'):
        error = value['error']
        return _public_error(error.get('code', '') if isinstance(error, dict) else '')
    return None


def _cancel(cancelled):
    return cancelled is not None and cancelled.is_set()


def _request_spec(text, settings):
    # Re-validate even a programmatic config; it cannot provide an arbitrary endpoint.
    fields = config_store._validated(settings)
    key = settings.get('apiKey')
    if not isinstance(key, str) or not __import__('re').fullmatch(r'[A-Za-z0-9_.-]{16,512}', key):
        raise EngineError('API_KEY_NOT_CONFIGURED', '请先在控制台保存有效的阿里云 API Key。', 400)
    if fields['mode'] == 'simple':
        host = 'dashscope.aliyuncs.com' if fields['region'] == 'beijing' else 'dashscope-intl.aliyuncs.com'
        url = 'https://' + host + '/api/v1/services/aigc/multimodal-generation/generation'
        body = {'model': 'qwen3-tts-flash', 'input': {'text': text, 'voice': fields['voice'], 'language_type': 'Chinese'}}
    else:
        if not fields['apiHost']:
            raise EngineError('API_HOST_NOT_CONFIGURED', '情绪语音需要填写百炼控制台的 API Host。', 400)
        url = fields['apiHost'] + '/api/v1/services/audio/tts/SpeechSynthesizer'
        body = {'model': 'qwen-audio-3.1-tts-flash', 'input': {'text': text, 'voice': fields['voice'],
                'format': 'wav', 'sample_rate': SAMPLE_RATE, 'rate': 1.0,
                'instruction': fields['instruction'] or STYLE_INSTRUCTIONS[fields['style']]}}
    request = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode('utf-8'), method='POST',
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json', 'Accept': 'text/event-stream',
                 'X-DashScope-SSE': 'enable', 'User-Agent': 'AIRI-Aliyun-TTS/1.0'})
    return request, fields, body['model']


def _events(response, cancelled, started):
    data = []
    size = 0
    while True:
        if _cancel(cancelled):
            raise EngineError('REQUEST_CANCELLED', '语音请求已取消。', 499)
        if time.perf_counter() - started > MAX_SECONDS:
            raise EngineError('UPSTREAM_TIMEOUT', '阿里语音等待超时，请稍后重试。', 504)
        raw = response.readline(MAX_EVENT + 1)
        if len(raw) > MAX_EVENT:
            raise EngineError('UPSTREAM_EVENT_TOO_LARGE', '阿里语音返回数据过大，已停止。')
        if not raw:
            if data:
                yield '\n'.join(data)
            return
        try:
            line = raw.decode('utf-8').rstrip('\r\n')
        except UnicodeError:
            raise EngineError('INVALID_UPSTREAM_EVENT', '阿里语音返回格式无效。') from None
        if line == '':
            if data:
                yield '\n'.join(data)
                data, size = [], 0
            continue
        if line.startswith('data:'):
            part = line[5:].lstrip(' ')
            size += len(part)
            if size > MAX_EVENT:
                raise EngineError('UPSTREAM_EVENT_TOO_LARGE', '阿里语音返回数据过大，已停止。')
            data.append(part)


def _pcm_wav(pcm, rate=SAMPLE_RATE, channels=1, width=2):
    if not pcm or len(pcm) % (channels * width):
        raise EngineError('INVALID_PCM_AUDIO', '阿里语音音频不完整，请重试。')
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(channels); wav.setsampwidth(width); wav.setframerate(rate); wav.writeframes(pcm)
    return output.getvalue(), len(pcm) / (channels * width * rate)


def _normalize_streaming_wav(data):
    """Normalize only the exact streaming header observed from Qwen Audio.

    This does not establish completeness. The caller must first receive the
    protocol's successful finish_reason=stop. Unknown sizes remain invalid.
    """
    if (len(data) < 44 or data[:4] != b'RIFF' or data[8:12] != b'WAVE'
            or struct.unpack_from('<I', data, 4)[0] != 0x7FFFFFBF):
        return data
    if (data[12:16] != b'fmt ' or struct.unpack_from('<I', data, 16)[0] != 16
            or data[36:40] != b'data' or struct.unpack_from('<I', data, 40)[0] != 0x7FFFFF9B):
        raise EngineError('UNSUPPORTED_WAV_CONTAINER', '情绪语音返回了未知的流式 WAV 头。')
    # This observed placeholder is specifically canonical PCM16 mono 24 kHz.
    # Do not infer PCM layout from unknown or inconsistent format fields.
    if struct.unpack_from('<HHIIHH', data, 20) != (1, 1, SAMPLE_RATE, SAMPLE_RATE * 2, 2, 16):
        raise EngineError('UNSUPPORTED_WAV_FORMAT', '情绪语音的流式音频格式暂不支持。')
    payload_size = len(data) - 44
    if payload_size <= 0 or payload_size % 2:
        raise EngineError('INCOMPLETE_WAV_AUDIO', '情绪语音返回的流式音频帧不完整。')
    # A second recognizable WAV header has no trusted boundary after a size
    # placeholder. Reject that ambiguity rather than treating it as PCM.
    embedded = data.find(b'RIFF', 44)
    while embedded != -1:
        if data[embedded + 8:embedded + 16] == b'WAVEfmt ':
            raise EngineError('UNSUPPORTED_WAV_CONTAINER', '流式 WAV 片段边界不明确，请重试。')
        embedded = data.find(b'RIFF', embedded + 4)
    normalized = bytearray(data)
    struct.pack_into('<I', normalized, 4, len(data) - 8)
    struct.pack_into('<I', normalized, 40, payload_size)
    return bytes(normalized)


def _validated_wav(data, *, allow_streaming_placeholder=False):
    # The expressive model's raw PCM sample format is not documented. Request
    # WAV and validate complete containers instead of guessing byte layout.
    if allow_streaming_placeholder:
        data = _normalize_streaming_wav(data)
    offset = 0
    pcm_parts = []
    parameters = None
    while offset < len(data):
        if data[offset:offset + 4] != b'RIFF' or data[offset + 8:offset + 12] != b'WAVE' or len(data) - offset < 44:
            raise EngineError('UNSUPPORTED_WAV_CONTAINER', '情绪语音返回的 WAV 容器暂不支持，请切回标准模式。')
        length = struct.unpack_from('<I', data, offset + 4)[0] + 8
        if length < 44 or length > len(data) - offset:
            raise EngineError('INCOMPLETE_WAV_AUDIO', '情绪语音返回的 WAV 音频不完整，请重试或切回标准模式。')
        try:
            with wave.open(io.BytesIO(data[offset:offset + length]), 'rb') as wav:
                current = (wav.getframerate(), wav.getnchannels(), wav.getsampwidth())
                if wav.getcomptype() != 'NONE' or current[0] != SAMPLE_RATE or current[1] not in (1, 2) or current[2] not in (1, 2, 3, 4):
                    raise EngineError('UNSUPPORTED_WAV_FORMAT', '情绪语音的音频格式暂不支持，请切回标准模式。')
                frames = wav.readframes(wav.getnframes())
                if len(frames) != wav.getnframes() * current[1] * current[2]:
                    raise EngineError('INCOMPLETE_WAV_AUDIO', '情绪语音返回的音频不完整。')
                if parameters is not None and current != parameters:
                    raise EngineError('INCONSISTENT_WAV_FORMAT', '情绪语音各片段格式不一致，请切回标准模式。')
                parameters = current
                pcm_parts.append(frames)
        except (wave.Error, EOFError, struct.error):
            raise EngineError('INVALID_WAV_AUDIO', '情绪语音返回了无效 WAV 音频。') from None
        offset += length
    if parameters is None:
        raise EngineError('EMPTY_UPSTREAM_AUDIO', '阿里语音没有返回音频。')
    return _pcm_wav(b''.join(pcm_parts), *parameters)


def synthesize(text, config=None, cancel=None, *, opener=None):
    if (not isinstance(text, str) or not text.strip() or len(text) > 600
            or any(ord(char) < 32 and char not in '\n\r\t' for char in text)):
        raise EngineError('INVALID_TEXT', '单次语音请输入 1 至 600 个字符。', 400)
    if _cancel(cancel):
        raise EngineError('REQUEST_CANCELLED', '语音请求已取消。', 499)
    try:
        settings = config if config is not None else config_store.load_private_settings()
        request, fields, model = _request_spec(text, settings)
    except config_store.ConfigError as error:
        raise EngineError(error.code, str(error), 400) from None
    if opener is None:
        opener = urllib.request.build_opener(NoRedirect())
    started = time.perf_counter()
    first_audio = None
    chunks = []
    byte_count = 0
    stopped = False
    response = None
    finished = threading.Event()
    try:
        response = opener.open(request, timeout=25)
        content_type = response.headers.get('Content-Type', '').lower()
        if 'text/event-stream' not in content_type:
            try:
                value = json.loads(response.read(16385))
            except (ValueError, UnicodeError):
                value = None
            error = _error_object(value)
            raise error or EngineError('SSE_REQUIRED', '阿里语音未返回流式音频，请检查模式和 API Host。')

        def watch_cancel():
            while not finished.wait(.1):
                if _cancel(cancel) or time.perf_counter() - started > MAX_SECONDS:
                    try:
                        response.close()
                    except Exception:
                        pass
                    return
        threading.Thread(target=watch_cancel, daemon=True).start()
        for raw in _events(response, cancel, started):
            if raw == '[DONE]':
                break
            try:
                event = json.loads(raw)
            except ValueError:
                raise EngineError('INVALID_UPSTREAM_EVENT', '阿里语音返回了无效数据。') from None
            error = _error_object(event)
            if error:
                raise error
            output = event.get('output') if isinstance(event, dict) else None
            if not isinstance(output, dict):
                raise EngineError('INVALID_UPSTREAM_EVENT', '阿里语音返回格式不完整。')
            audio = output.get('audio') or {}
            encoded = audio.get('data') if isinstance(audio, dict) else None
            if encoded:
                if not isinstance(encoded, str):
                    raise EngineError('INVALID_AUDIO_DATA', '阿里语音音频编码无效。')
                try:
                    part = base64.b64decode(encoded, validate=True)
                except (ValueError, binascii.Error):
                    raise EngineError('INVALID_AUDIO_DATA', '阿里语音音频编码无效。') from None
                if part:
                    first_audio = time.perf_counter() if first_audio is None else first_audio
                    byte_count += len(part)
                    if byte_count > MAX_AUDIO:
                        raise EngineError('UPSTREAM_AUDIO_TOO_LARGE', '语音音频过长，已停止。')
                    chunks.append(part)
            if output.get('finish_reason') == 'stop':
                stopped = True
                break
        if _cancel(cancel):
            raise EngineError('REQUEST_CANCELLED', '语音请求已取消。', 499)
        if not stopped:
            raise EngineError('INCOMPLETE_UPSTREAM_AUDIO', '阿里语音未完整结束，请重试。')
        if first_audio is None:
            raise EngineError('EMPTY_UPSTREAM_AUDIO', '阿里语音没有返回音频，请检查模型和音色。')
        data = b''.join(chunks)
        wav, duration = _pcm_wav(data) if fields['mode'] == 'simple' else _validated_wav(data, allow_streaming_placeholder=stopped)
        elapsed = time.perf_counter() - started
        return {'wav': wav, 'model': model, 'voice': fields['voice'], 'configRevision': settings.get('revision'),
                'timings': {'firstAudioMs': round((first_audio - started) * 1000, 3),
                            'completeWavMs': round(elapsed * 1000, 3), 'audioDurationSeconds': round(duration, 6)}}
    except urllib.error.HTTPError as error:
        try:
            value = json.loads(error.read(16385))
            mapped = _error_object(value)
        except (ValueError, UnicodeError, OSError):
            mapped = None
        if mapped:
            raise mapped from None
        if error.code in (401, 403):
            raise _public_error('UNAUTHORIZED') from None
        if error.code == 429:
            raise _public_error('RATE_LIMIT') from None
        raise EngineError('ALIYUN_HTTP_ERROR', '阿里语音服务暂时未完成请求，请稍后重试。') from None
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
        if _cancel(cancel):
            raise EngineError('REQUEST_CANCELLED', '语音请求已取消。', 499) from None
        raise EngineError('ALIYUN_CONNECTION_FAILED', '无法连接阿里语音，请检查网络和所选地域。', 504) from None
    finally:
        finished.set()
        if response is not None:
            response.close()
        chunks.clear()


def test_synthesis(root=None, *, opener=None):
    try:
        settings = config_store.load_private_settings(root)
    except config_store.ConfigError as error:
        raise EngineError(error.code, str(error), 400) from None
    return {**synthesize(TEST_TEXT, settings, opener=opener), 'text': TEST_TEXT}
