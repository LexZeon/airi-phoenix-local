#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Optional authenticated loopback WAV adapter for Aliyun cloud speech."""
from __future__ import annotations

import argparse
import hmac
import importlib.util
import json
import os
from pathlib import Path
import queue
import re
import select
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
MODEL = 'aliyun-qwen-tts'
MAX_BODY = 32000
MAX_AUDIO = 17 * 1024 * 1024


def _module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


config_store = _module('airi_aliyun_server_configuration', 'aliyun_config.py')
engine = _module('airi_aliyun_server_engine', 'engine.py')


class RequestError(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status


def normalize_request(value):
    if not isinstance(value, dict):
        raise RequestError('INVALID_REQUEST', '语音请求无效。')
    if value.get('model', MODEL) != MODEL:
        raise RequestError('UNKNOWN_MODEL', '这个接口只接受阿里语音模型。')
    text = value.get('input')
    if not isinstance(text, str) or not text.strip() or len(text) > 600:
        raise RequestError('INVALID_TEXT', '单次语音需要 1 至 600 个字符。')
    if value.get('response_format', 'wav') != 'wav':
        raise RequestError('WAV_REQUIRED', '阿里语音连接目前只输出 WAV。')
    speed = value.get('speed', 1)
    if isinstance(speed, bool) or not isinstance(speed, (int, float)) or speed != 1:
        raise RequestError('UNSUPPORTED_SPEED', '请使用默认播放速度；情绪语音的语速可在阿里设置中调整语气。')
    voice = value.get('voice', 'configured')
    if not isinstance(voice, str) or len(voice) > 100:
        raise RequestError('INVALID_VOICE', '音色参数无效。')
    return text, voice


class Adapter:
    def __init__(self, config_module=config_store, engine_module=engine):
        self.config, self.engine = config_module, engine_module
        self.capacity = threading.BoundedSemaphore(2)
        self.lock = threading.RLock()
        self.active = set()
        self.stopping = threading.Event()
        self.last_error = None
        self.metrics = {'requests': 0, 'completed': 0, 'failed': 0, 'cancelled': 0, 'busy_rejections': 0,
                        'lastFirstAudioMs': None, 'lastCompleteWavMs': None, 'lastAudioDurationSeconds': None}

    def public_config(self):
        return self.config.get_public_settings()

    def begin(self, text, voice):
        if self.stopping.is_set():
            raise RequestError('SERVICE_STOPPING', '语音服务正在停止。', 503)
        if not self.capacity.acquire(blocking=False):
            with self.lock:
                self.metrics['busy_rejections'] += 1
            raise RequestError('SPEECH_BUSY', '阿里语音正在处理其他句子，请稍后重试。', 429)
        cancelled = threading.Event()
        job = {'cancelled': cancelled, 'finished': threading.Event(), 'result': queue.Queue(maxsize=1), 'started': time.monotonic()}
        with self.lock:
            self.active.add(cancelled)
            self.metrics['requests'] += 1

        def run():
            kind = 'failed'
            try:
                settings = self.config.load_private_settings()
                if voice not in ('configured', settings['voice']):
                    raise RequestError('VOICE_MISMATCH', '请在控制台选择并保存所需音色。')
                result = self.engine.synthesize(text, settings, cancelled)
                if not isinstance(result, dict) or not isinstance(result.get('wav'), bytes) or not 44 <= len(result['wav']) <= MAX_AUDIO or result['wav'][:4] != b'RIFF':
                    raise RequestError('INVALID_UPSTREAM_AUDIO', '阿里语音未返回有效 WAV。', 502)
                if cancelled.is_set():
                    kind = 'cancelled'
                else:
                    job['result'].put(('audio', result))
                    kind = 'completed'
                    with self.lock:
                        timings = result.get('timings', {})
                        self.metrics['lastFirstAudioMs'] = timings.get('firstAudioMs')
                        self.metrics['lastCompleteWavMs'] = timings.get('completeWavMs')
                        self.metrics['lastAudioDurationSeconds'] = timings.get('audioDurationSeconds')
                        self.last_error = None
            except (self.config.ConfigError, self.engine.EngineError, RequestError) as error:
                if cancelled.is_set():
                    kind = 'cancelled'
                else:
                    code = getattr(error, 'code', 'SPEECH_FAILED')
                    code = code if isinstance(code, str) and re.fullmatch('[A-Z_0-9]{1,80}', code) else 'SPEECH_FAILED'
                    status = getattr(error, 'status', 400)
                    status = status if status in (400, 401, 402, 403, 429, 499, 502, 503, 504) else 502
                    # Only errors defined by our local modules supply the user message.
                    job['result'].put(('error', RequestError(code, str(error), status)))
                    with self.lock:
                        self.last_error = code
            except Exception:
                if not cancelled.is_set():
                    job['result'].put(('error', RequestError('SPEECH_FAILED', '阿里语音请求未完成，请检查配置后重试。', 502)))
                    with self.lock:
                        self.last_error = 'SPEECH_FAILED'
                else:
                    kind = 'cancelled'
            finally:
                with self.lock:
                    self.active.discard(cancelled)
                    self.metrics[kind] += 1
                job['finished'].set()
                self.capacity.release()
        threading.Thread(target=run, daemon=True).start()
        return job

    def close(self):
        self.stopping.set()
        with self.lock:
            for cancel in list(self.active):
                cancel.set()

    def snapshot(self):
        try:
            settings = self.public_config()
            configured, key_configured = settings['configured'], settings['keyConfigured']
        except Exception:
            configured = key_configured = False
        with self.lock:
            return {'ready': not self.stopping.is_set(), 'configured': configured, 'keyConfigured': key_configured,
                    'online': True, 'offline': False, 'requests_active': len(self.active), 'last_error_code': self.last_error,
                    'metrics': self.metrics.copy(), 'upstream_streaming': True, 'client_delivery': 'complete-wav',
                    'actual_airi_playback_latency_measured': False}


def make_handler(adapter, token, launch_id, port):
    hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
    origins = {'null', f'http://127.0.0.1:{port}', f'http://localhost:{port}', 'http://127.0.0.1:9944', 'http://localhost:9944'}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        server_version = 'AiriAliyunTts/1.0'

        def log_message(self, *_):
            pass

        def gate(self):
            host_values = self.headers.get_all('Host', [])
            origin_values = self.headers.get_all('Origin', [])
            if len(host_values) != 1 or host_values[0] not in hosts or len(origin_values) > 1 or (origin_values and origin_values[0] not in origins):
                self.error(403, 'ORIGIN_DENIED', '请求来源不受支持。')
                return False
            return True

        def authorized(self):
            values = self.headers.get_all('Authorization', [])
            return len(values) == 1 and hmac.compare_digest(values[0].encode('utf-8'), ('Bearer ' + token).encode('ascii'))

        def send_headers(self, status, content_type, length):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(length))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Connection', 'close')
            origin = self.headers.get('Origin')
            if origin in origins:
                self.send_header('Access-Control-Allow-Origin', origin)
                self.send_header('Vary', 'Origin')
                self.send_header('Access-Control-Allow-Methods', 'GET, HEAD, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
            self.end_headers()
            self.close_connection = True

        def json(self, status, value):
            body = json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.send_headers(status, 'application/json; charset=utf-8', len(body))
            if self.command != 'HEAD':
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

        def error(self, status, code, message):
            # Drain only a bounded, already sent short body, preventing a Windows TCP reset
            # from obscuring an authentication error. Never log or parse this body.
            if self.command == 'POST' and not getattr(self, '_body_read', False):
                try:
                    lengths = self.headers.get_all('Content-Length', [])
                    length = int(lengths[0]) if len(lengths) == 1 else 0
                    if not self.headers.get('Transfer-Encoding') and 0 < length <= MAX_BODY:
                        self.connection.settimeout(.1)
                        self.rfile.read(length)
                        self._body_read = True
                except (ValueError, OSError):
                    pass
            self.json(status, {'error': {'type': 'aliyun_tts_error', 'code': code, 'message': message}})

        def do_OPTIONS(self):
            if not self.gate():
                return
            requested = {part.strip().lower() for part in self.headers.get('Access-Control-Request-Headers', '').split(',') if part.strip()}
            if self.headers.get('Access-Control-Request-Method', 'POST') not in ('GET', 'HEAD', 'POST') or not requested.issubset({'authorization', 'content-type'}):
                self.error(403, 'PREFLIGHT_DENIED', '该请求头不受支持。')
                return
            self.send_headers(204, 'application/json', 0)

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            if not self.gate():
                return
            if self.path == '/health':
                self.json(200, {'service': 'airi-aliyun-tts', 'instance_id': launch_id, 'pid': os.getpid(), 'model': MODEL, **adapter.snapshot()})
            elif self.path == '/v1/models':
                self.json(200, {'object': 'list', 'data': [{'id': MODEL, 'object': 'model', 'owned_by': 'local-aliyun-adapter', 'name': 'Aliyun online speech'}]})
            elif self.path == '/v1/audio/voices':
                try:
                    settings = adapter.public_config()
                    self.json(200, {'object': 'list', 'data': [{'id': 'configured', 'name': settings['voice'], 'language': 'zh-CN'}]})
                except Exception:
                    self.error(503, 'CONFIG_UNAVAILABLE', '阿里语音配置不可用。')
            else:
                self.error(404, 'NOT_FOUND', '接口不存在。')

        def read_json(self):
            if self.headers.get('Content-Type', '').split(';', 1)[0].strip().lower() != 'application/json':
                raise RequestError('JSON_REQUIRED', '需要 JSON 请求。', 415)
            lengths = self.headers.get_all('Content-Length', [])
            if len(lengths) != 1 or self.headers.get('Transfer-Encoding'):
                raise RequestError('INVALID_LENGTH', '请求长度无效。')
            try:
                length = int(lengths[0])
                if not 0 < length <= MAX_BODY:
                    raise RequestError('REQUEST_TOO_LARGE', '请求内容过长。', 413)
                self.connection.settimeout(5)
                raw = self.rfile.read(length)
                self._body_read = True
                if len(raw) != length:
                    raise ValueError()
                return json.loads(raw.decode('utf-8'))
            except RequestError:
                raise
            except (ValueError, UnicodeError, OSError):
                raise RequestError('INVALID_JSON', 'JSON 请求无效。') from None

        def client_closed(self):
            try:
                ready, _, _ = select.select([self.connection], [], [], 0)
                return bool(ready and self.connection.recv(1, socket.MSG_PEEK) == b'')
            except OSError:
                return True

        def do_POST(self):
            if not self.gate():
                return
            if self.path not in ('/v1/audio/speech', '/internal/shutdown'):
                self.error(404, 'NOT_FOUND', '接口不存在。')
                return
            if not self.authorized():
                self.error(401, 'AUTH_REQUIRED', '本机语音连接需要密钥。')
                return
            job = None
            try:
                data = self.read_json()
                if self.path == '/internal/shutdown':
                    if data != {}:
                        raise RequestError('INVALID_REQUEST', '停止请求无效。')
                    adapter.close()
                    self.json(200, {'ok': True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                text, voice = normalize_request(data)
                job = adapter.begin(text, voice)
                while True:
                    if self.client_closed() or adapter.stopping.is_set():
                        job['cancelled'].set()
                        return
                    if time.monotonic() - job['started'] > 100:
                        job['cancelled'].set()
                        raise RequestError('REQUEST_TIMEOUT', '阿里语音等待超时。', 504)
                    try:
                        kind, result = job['result'].get(timeout=.05)
                        break
                    except queue.Empty:
                        if job['finished'].is_set():
                            raise RequestError('REQUEST_CANCELLED', '语音请求已取消。', 499)
                if kind == 'error':
                    raise result
                self.send_headers(200, 'audio/wav', len(result['wav']))
                try:
                    self.wfile.write(result['wav'])
                except OSError:
                    job['cancelled'].set()
            except RequestError as error:
                self.error(error.status, error.code, error.message)
            except Exception:
                self.error(502, 'SPEECH_FAILED', '阿里语音请求未完成，请重试。')
            finally:
                if job and not job['finished'].is_set():
                    job['cancelled'].set()

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', choices=['127.0.0.1'], default='127.0.0.1')
    parser.add_argument('--port', choices=[9949], type=int, default=9949)
    parser.add_argument('--launch-id', required=True)
    arguments = parser.parse_args()
    if not re.fullmatch('[a-f0-9]{32}', arguments.launch_id):
        parser.error('Invalid launch identity')
    adapter = Adapter()
    token = config_store.ensure_token()
    server = ThreadingHTTPServer((arguments.host, arguments.port), make_handler(adapter, token, arguments.launch_id, arguments.port))
    server.daemon_threads = True
    try:
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:
        pass
    finally:
        adapter.close()
        server.server_close()


if __name__ == '__main__':
    main()
