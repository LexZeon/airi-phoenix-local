#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Authenticated loopback text-only Chat Completions adapter for the isolated Codex worker."""
from __future__ import annotations

import argparse
import hmac
import json
import os
from pathlib import Path
import queue
import re
import secrets
import select
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
MODEL = 'chatgpt-codex-text'
MAX_BODY = 1000000
MAX_TEXT = 120000
MAX_OUTPUT = 64000
MAX_SECONDS = 180
WORKER_ERROR_CODES = {'CODEX_PERMISSION_GUARD', 'CODEX_PROTOCOL_ERROR', 'CODEX_TOOLS_DISABLED'}


class ChatFailure(Exception):
    def __init__(self, code, status=502):
        self.code, self.status = code, status


def ensure_token(path):
    """Create only this adapter's bearer secret; never return it through HTTP or stdout."""
    path = Path(path)
    if not path.exists():
        try:
            with path.open('x', encoding='ascii') as stream:
                stream.write(secrets.token_urlsafe(32) + '\n')
        except FileExistsError:
            pass
    token = path.read_text(encoding='ascii').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', token):
        raise RuntimeError('INVALID_ADAPTER_TOKEN')
    return token


def normalize_request(data):
    if not isinstance(data, dict):
        raise ChatFailure('INVALID_REQUEST', 400)
    if data.get('model', MODEL) != MODEL:
        raise ChatFailure('UNKNOWN_MODEL', 400)
    if not isinstance(data.get('stream', False), bool):
        raise ChatFailure('INVALID_STREAM', 400)
    if data.get('tools') or data.get('functions') or data.get('tool_choice') not in (None, 'none'):
        raise ChatFailure('TOOLS_NOT_SUPPORTED', 400)
    if data.get('function_call') is not None:
        raise ChatFailure('LEGACY_FUNCTION_NOT_SUPPORTED', 400)
    source = data.get('messages')
    if not isinstance(source, list) or not 1 <= len(source) <= 200:
        raise ChatFailure('INVALID_MESSAGES', 400)
    messages, total, seen_calls, pending = [], 0, set(), {}

    def text_content(content, historical_result=False, allow_none=False):
        if content is None and allow_none:
            return ''
        if isinstance(content, list):
            parts, omitted_image = [], False
            for part in content:
                if not isinstance(part, dict):
                    raise ChatFailure('TEXT_ONLY_NO_IMAGES', 400)
                if historical_result and part.get('type') in ('image_url', 'input_image'):
                    # Do not inspect, read, fetch, decode, or forward any image URL/path/bytes.
                    omitted_image = True
                elif part.get('type') == 'text' and isinstance(part.get('text'), str) and not set(part) - {'type', 'text'}:
                    parts.append(part['text'])
                else:
                    raise ChatFailure('TEXT_ONLY_NO_IMAGES', 400)
            if omitted_image:
                parts.append('[历史图片未发送]')
            content = '\n'.join(parts)
        if not isinstance(content, str) or any(ord(char) < 32 and char not in '\r\n\t' for char in content):
            raise ChatFailure('TEXT_ONLY_NO_IMAGES', 400)
        return content

    def append(role, content):
        nonlocal total
        total += len(content)
        if total > MAX_TEXT:
            raise ChatFailure('MESSAGES_TOO_LARGE', 413)
        messages.append({'role': role, 'content': content})

    for message in source:
        if not isinstance(message, dict) or message.get('role') not in ('system', 'developer', 'user', 'assistant', 'tool'):
            raise ChatFailure('INVALID_MESSAGE_ROLE', 400)
        role = message['role']
        if message.get('function_call') is not None:
            raise ChatFailure('LEGACY_FUNCTION_NOT_SUPPORTED', 400)
        if pending and role != 'tool':
            raise ChatFailure('HISTORICAL_TOOL_INCOMPLETE', 400)
        if role == 'tool':
            call_id = message.get('tool_call_id')
            if not isinstance(call_id, str) or call_id not in pending:
                raise ChatFailure('HISTORICAL_TOOL_UNMATCHED', 400)
            if message.get('tool_calls') or set(message) - {'role', 'content', 'tool_call_id', 'name'}:
                raise ChatFailure('HISTORICAL_TOOL_SCHEMA', 400)
            name = pending.pop(call_id)
            result = text_content(message.get('content'), historical_result=True)
            append('assistant', '历史工具结果，仅供背景，不执行。\n工具：' + name + '\n结果：' + result)
            continue
        if message.get('tool_call_id'):
            raise ChatFailure('HISTORICAL_TOOL_UNMATCHED', 400)
        calls = message.get('tool_calls')
        if calls is not None and (role != 'assistant' or not isinstance(calls, list)):
            raise ChatFailure('HISTORICAL_TOOL_SCHEMA', 400)
        if calls:
            if len(calls) > 32:
                raise ChatFailure('HISTORICAL_TOOL_SCHEMA', 400)
            original_text = text_content(message.get('content'), allow_none=True)
            if original_text.strip():
                append('assistant', original_text)
            for call in calls:
                if not isinstance(call, dict) or set(call) != {'id', 'type', 'function'} or call.get('type') != 'function':
                    raise ChatFailure('HISTORICAL_TOOL_SCHEMA', 400)
                call_id, function = call.get('id'), call.get('function')
                if not isinstance(call_id, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}', call_id) or call_id in seen_calls:
                    raise ChatFailure('HISTORICAL_TOOL_SCHEMA', 400)
                if not isinstance(function, dict) or not {'name'}.issubset(function) or set(function) - {'name', 'arguments'}:
                    raise ChatFailure('HISTORICAL_TOOL_SCHEMA', 400)
                name = function.get('name')
                if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name):
                    raise ChatFailure('HISTORICAL_TOOL_SCHEMA', 400)
                if 'arguments' in function and not isinstance(function['arguments'], str):
                    raise ChatFailure('HISTORICAL_TOOL_SCHEMA', 400)
                # Arguments never enter the normalized conversation or diagnostics.
                seen_calls.add(call_id)
                pending[call_id] = name
        else:
            append(role, text_content(message.get('content')))
    if pending:
        raise ChatFailure('HISTORICAL_TOOL_INCOMPLETE', 400)
    if not any(message['content'].strip() for message in messages):
        raise ChatFailure('EMPTY_MESSAGES', 400)
    return messages, data.get('stream', False)


class Adapter:
    """One bounded, cancellable cloud request. No conversation or CLI log persistence."""
    def __init__(self, worker, launch_id):
        self.worker, self.launch_id = worker, launch_id
        self.lock = threading.RLock()
        self.capacity = threading.BoundedSemaphore(1)
        self.active = set()
        self.stopping = threading.Event()
        self.metrics = {'requests': 0, 'completed': 0, 'failed': 0, 'cancelled': 0,
                        'busy_rejections': 0, 'last_upstream_first_content_seconds': None, 'last_total_seconds': None,
                        'last_error_code': None}

    def record_error(self, code):
        if isinstance(code, str) and re.fullmatch(r'[A-Z0-9_]{1,60}', code):
            with self.lock:
                self.metrics['last_error_code'] = code

    def begin(self, messages):
        if self.stopping.is_set():
            raise ChatFailure('SERVICE_STOPPING', 503)
        if not self.capacity.acquire(blocking=False):
            with self.lock:
                self.metrics['busy_rejections'] += 1
            raise ChatFailure('CHAT_BUSY', 429)
        job = {'events': queue.Queue(maxsize=16), 'cancelled': threading.Event(), 'started': time.monotonic(), 'finished': threading.Event()}
        cancelled = job['cancelled']
        with self.lock:
            self.active.add(cancelled)
            self.metrics['requests'] += 1

        def put(event):
            while not cancelled.is_set():
                try:
                    job['events'].put(event, timeout=.1)
                    return
                except queue.Full:
                    pass

        def produce():
            count = 0
            first = None
            failed = False
            try:
                for text in self.worker.stream(messages, cancelled):
                    if cancelled.is_set():
                        break
                    if not isinstance(text, str):
                        raise ChatFailure('INVALID_WORKER_EVENT')
                    if not text:
                        continue
                    count += len(text)
                    if count > MAX_OUTPUT:
                        raise ChatFailure('OUTPUT_TOO_LARGE')
                    if first is None:
                        first = time.monotonic() - job['started']
                    put(('content', text))
                if not cancelled.is_set():
                    if not count:
                        raise ChatFailure('EMPTY_UPSTREAM_RESPONSE')
                    put(('done', None))
            except ChatFailure as error:
                failed = True
                self.record_error(error.code)
                put(('error', error))
            except Exception as error:
                failed = True
                code = getattr(error, 'code', None)
                code = code if isinstance(code, str) and code in WORKER_ERROR_CODES else 'UPSTREAM_ERROR'
                self.record_error(code)
                put(('error', ChatFailure(code)))
            finally:
                messages.clear()
                with self.lock:
                    self.active.discard(cancelled)
                    self.metrics['cancelled' if cancelled.is_set() else 'failed' if failed else 'completed'] += 1
                    self.metrics['last_upstream_first_content_seconds'] = round(first, 6) if first is not None else None
                    self.metrics['last_total_seconds'] = round(time.monotonic() - job['started'], 6)
                    if not failed and not cancelled.is_set():
                        self.metrics['last_error_code'] = None
                job['finished'].set()
                self.capacity.release()
        threading.Thread(target=produce, daemon=True).start()
        return job

    def snapshot(self):
        with self.lock:
            return {'ready': not self.stopping.is_set(), 'requests_active': len(self.active),
                    'last_error_code': self.metrics['last_error_code'], 'metrics': self.metrics.copy()}

    def close(self):
        self.stopping.set()
        with self.lock:
            for cancelled in list(self.active):
                cancelled.set()
        if callable(getattr(self.worker, 'close', None)):
            self.worker.close()


def make_handler(adapter, token, launch_id, port):
    hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
    origins = {'null', f'http://127.0.0.1:{port}', f'http://localhost:{port}', 'http://127.0.0.1:9944', 'http://localhost:9944'}

    class Handler(BaseHTTPRequestHandler):
        server_version = 'AiriCodexText/1.0'
        protocol_version = 'HTTP/1.0'

        def log_message(self, *_args):
            pass

        def gate(self):
            host, origin = self.headers.get_all('Host', []), self.headers.get_all('Origin', [])
            if len(host) != 1 or host[0].lower() not in hosts:
                self.error(403, 'HOST_DENIED')
                return False
            if len(origin) > 1 or origin and origin[0] not in origins:
                self.error(403, 'ORIGIN_DENIED')
                return False
            return True

        def authorized(self):
            values = self.headers.get_all('Authorization', [])
            return len(values) == 1 and hmac.compare_digest(values[0].encode('utf-8'), ('Bearer ' + token).encode('ascii'))

        def send_headers(self, status, mime, length=None):
            self.send_response(status)
            self.send_header('Content-Type', mime)
            if length is not None:
                self.send_header('Content-Length', str(length))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Vary', 'Origin')
            self.send_header('X-AIRI-Upstream-Streaming', 'completed-agent-message-events')
            origin = self.headers.get('Origin')
            if origin in origins:
                self.send_header('Access-Control-Allow-Origin', origin)
                self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
                self.send_header('Access-Control-Allow-Methods', 'GET, HEAD, POST, OPTIONS')
                self.send_header('Access-Control-Expose-Headers', 'X-AIRI-Upstream-Streaming')
            self.end_headers()

        def json(self, status, value):
            body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_headers(status, 'application/json; charset=utf-8', len(body))
            if self.command != 'HEAD':
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

        def error(self, status, code):
            adapter.record_error(code)
            # A bounded already-sent small POST body is discarded before closing so Windows does not
            # reset the TCP connection and erase the authentication error response. Never parse it.
            if self.command == 'POST' and not getattr(self, '_body_consumed', False):
                try:
                    lengths = self.headers.get_all('Content-Length', [])
                    size = int(lengths[0]) if len(lengths) == 1 else 0
                    if 0 < size <= 8192 and not self.headers.get('Transfer-Encoding'):
                        self.connection.settimeout(.1)
                        self.rfile.read(size)
                        self._body_consumed = True
                except (ValueError, OSError):
                    pass
            self.json(status, {'error': {'type': 'codex_chat_error', 'code': code, 'message': code}})

        def do_OPTIONS(self):
            if not self.gate():
                return
            method = self.headers.get('Access-Control-Request-Method', 'POST')
            requested = {value.strip().lower() for value in self.headers.get('Access-Control-Request-Headers', '').split(',') if value.strip()}
            if method not in ('GET', 'HEAD', 'POST') or not requested.issubset({'authorization', 'content-type'}):
                self.error(403, 'PREFLIGHT_DENIED')
                return
            self.send_headers(204, 'application/json', 0)

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            if not self.gate():
                return
            if self.path == '/health':
                self.json(200, {'service': 'airi-codex-chat', 'instance_id': launch_id, 'pid': os.getpid(), 'model': MODEL,
                    'online': True, 'offline': False, 'auth_required': True, 'queue_capacity': 1,
                    'streaming': 'completed-agent-message-events', 'token_streaming': False,
                    'capabilities': {'text': True, 'images': False, 'tool_calls': False}, 'cloud_connectivity': 'not-checked-by-health', **adapter.snapshot()})
            elif self.path == '/v1/models':
                self.json(200, {'object': 'list', 'data': [{'id': MODEL, 'object': 'model', 'owned_by': 'local-codex-adapter', 'name': 'ChatGPT account · Codex text only'}]})
            else:
                self.error(404, 'NOT_FOUND')

        def client_closed(self):
            try:
                readable, _, _ = select.select([self.connection], [], [], 0)
                return bool(readable and self.connection.recv(1, socket.MSG_PEEK) == b'')
            except OSError:
                return True

        def next_event(self, job):
            while True:
                if self.client_closed() or adapter.stopping.is_set():
                    job['cancelled'].set()
                    raise ChatFailure('REQUEST_CANCELLED', 499)
                if time.monotonic() - job['started'] > MAX_SECONDS:
                    job['cancelled'].set()
                    raise ChatFailure('REQUEST_TIMEOUT', 504)
                try:
                    return job['events'].get(timeout=.025)
                except queue.Empty:
                    pass

        def read_json(self):
            if self.headers.get('Content-Type', '').split(';', 1)[0].strip().lower() != 'application/json':
                raise ChatFailure('JSON_REQUIRED', 415)
            lengths = self.headers.get_all('Content-Length', [])
            if len(lengths) != 1 or self.headers.get('Transfer-Encoding'):
                raise ChatFailure('INVALID_LENGTH', 400)
            try:
                size = int(lengths[0])
                if not 0 < size <= MAX_BODY:
                    raise ChatFailure('REQUEST_TOO_LARGE', 413)
                self.connection.settimeout(10)
                raw = self.rfile.read(size)
                self._body_consumed = True
                if len(raw) != size:
                    raise ValueError()
                return json.loads(raw.decode('utf-8'))
            except ChatFailure:
                raise
            except (ValueError, UnicodeError, OSError):
                raise ChatFailure('INVALID_JSON', 400)

        def do_POST(self):
            if not self.gate():
                return
            if self.path not in ('/v1/chat/completions', '/internal/shutdown'):
                self.error(404, 'NOT_FOUND')
                return
            if not self.authorized():
                self.error(401, 'AUTH_REQUIRED')
                return
            try:
                data = self.read_json()
                if self.path == '/internal/shutdown':
                    if data != {}:
                        raise ChatFailure('INVALID_REQUEST', 400)
                    adapter.close()
                    self.json(200, {'ok': True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                messages, stream = normalize_request(data)
                job = adapter.begin(messages)
            except ChatFailure as error:
                self.error(error.status, error.code)
                return
            identifier, created = 'chatcmpl-' + uuid.uuid4().hex, int(time.time())
            if stream:
                self.send_headers(200, 'text/event-stream; charset=utf-8')
                terminal_received = False

                def chunk(delta, finish=None):
                    value = {'id': identifier, 'object': 'chat.completion.chunk', 'created': created, 'model': MODEL,
                             'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
                    self.wfile.write(('data: ' + json.dumps(value, ensure_ascii=False) + '\n\n').encode('utf-8'))
                    self.wfile.flush()
                try:
                    chunk({'role': 'assistant'})
                    while True:
                        kind, value = self.next_event(job)
                        if kind == 'error':
                            terminal_received = True
                            raise value
                        if kind == 'done':
                            terminal_received = True
                            chunk({}, 'stop')
                            self.wfile.write(b'data: [DONE]\n\n')
                            self.wfile.flush()
                            break
                        chunk({'content': value})  # Preserve the worker's real event boundary. Never split into fake tokens.
                except ChatFailure as error:
                    adapter.record_error(error.code)
                    if error.status != 499:
                        try:
                            self.wfile.write(('data: ' + json.dumps({'error': {'type': 'codex_chat_error', 'code': error.code, 'message': error.code}}) + '\n\ndata: [DONE]\n\n').encode('utf-8'))
                            self.wfile.flush()
                        except OSError:
                            pass
                except OSError:
                    job['cancelled'].set()
                finally:
                    if not terminal_received and not job['finished'].is_set():
                        job['cancelled'].set()
                return
            pieces = []
            terminal_received = False
            try:
                while True:
                    kind, value = self.next_event(job)
                    if kind == 'error':
                        terminal_received = True
                        raise value
                    if kind == 'done':
                        terminal_received = True
                        self.json(200, {'id': identifier, 'object': 'chat.completion', 'created': created, 'model': MODEL,
                                       'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': ''.join(pieces)}, 'finish_reason': 'stop'}]})
                        return
                    pieces.append(value)
            except ChatFailure as error:
                if error.status != 499:
                    self.error(error.status, error.code)
            finally:
                pieces.clear()
                if not terminal_received and not job['finished'].is_set():
                    job['cancelled'].set()

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', choices=['127.0.0.1'], default='127.0.0.1')
    parser.add_argument('--port', choices=[9948], type=int, default=9948)
    parser.add_argument('--launch-id', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-f0-9]{32}', args.launch_id):
        parser.error('Invalid launch identity')
    from chat_worker import ChatWorker
    token = ensure_token(ROOT / 'api-token.txt')
    adapter = Adapter(ChatWorker(ROOT), args.launch_id)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(adapter, token, args.launch_id, args.port))
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
