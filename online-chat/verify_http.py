#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Temporary-port HTTP checks with a synthetic worker. Never starts CLI/cloud/production 9948."""
import contextlib
import http.client
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import server

TOKEN = 'synthetic-adapter-token-that-is-not-a-user-secret'
LAUNCH = '00000000111122223333444455555555'


class FakeWorker:
    def __init__(self, blocked=False, failure=False, error_code=None):
        self.release = threading.Event()
        if not blocked:
            self.release.set()
        self.started = threading.Event()
        self.cancelled = threading.Event()
        self.failure = failure
        self.error_code = error_code
        self.first_yield_at = None
        self.last_messages = None

    def stream(self, messages, cancelled):
        self.last_messages = [dict(item) for item in messages]
        self.started.set()
        while not self.release.wait(.01):
            if cancelled.is_set():
                self.cancelled.set()
                return
        if self.failure:
            error = RuntimeError('synthetic-private-error-must-not-appear-in-http')
            if self.error_code:
                error.code = self.error_code
            raise error
        self.first_yield_at = time.monotonic()
        yield 'first message'
        if cancelled.wait(.03):
            self.cancelled.set()
            return
        yield ' / second message'


@contextlib.contextmanager
def running(worker=None):
    worker = worker or FakeWorker()
    adapter = server.Adapter(worker, LAUNCH)
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), http.server.BaseHTTPRequestHandler)
    port = httpd.server_address[1]
    httpd.RequestHandlerClass = server.make_handler(adapter, TOKEN, LAUNCH, port)
    httpd.daemon_threads = True
    thread = threading.Thread(target=lambda: httpd.serve_forever(poll_interval=.02), daemon=True)
    thread.start()
    try:
        yield {'port': port, 'url': f'http://127.0.0.1:{port}', 'worker': worker, 'adapter': adapter}
    finally:
        adapter.close()
        httpd.shutdown()
        httpd.server_close()
        thread.join(1)


def payload(stream=False):
    return {'model': server.MODEL, 'messages': [{'role': 'system', 'content': 'Synthetic persona.'}, {'role': 'user', 'content': 'Synthetic hello.'}], 'stream': stream}


def history_call(identifier='call_previous', name='get_weather'):
    return {'id': identifier, 'type': 'function', 'function': {'name': name, 'arguments': '{"private_argument":"never-forward-this-argument"}'}}


def request(env, path, body=None, headers=None, raw=None):
    values = {'Origin': 'null', 'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json'}
    values.update(headers or {})
    data = json.dumps(body).encode('utf-8') if body is not None else raw
    req = urllib.request.Request(env['url'] + path, data=data, headers=values)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            data = response.read()
            return response.status, json.loads(data) if data else None, dict(response.headers)
    except urllib.error.HTTPError as error:
        data = error.read()
        return error.code, json.loads(data), dict(error.headers)


class HttpChecks(unittest.TestCase):
    def test_health_models_and_no_secret(self):
        with running() as env:
            code, health, headers = request(env, '/health')
            self.assertEqual(code, 200)
            self.assertTrue(health['online']); self.assertFalse(health['offline'])
            self.assertFalse(health['token_streaming'])
            self.assertEqual(health['streaming'], 'completed-agent-message-events')
            self.assertNotIn(TOKEN, json.dumps(health)); self.assertNotIn('Synthetic', json.dumps(health))
            self.assertEqual(headers.get('Access-Control-Allow-Origin'), 'null')
            self.assertEqual(request(env, '/v1/models')[1]['data'][0]['id'], server.MODEL)

    def test_auth_host_origin_and_preflight(self):
        with running() as env:
            for headers, expected in [({'Authorization': ''}, 401), ({'Authorization': 'Bearer wrong'}, 401),
                                      ({'Origin': 'https://example.org'}, 403)]:
                with self.subTest(kind=next(iter(headers))):
                    self.assertEqual(request(env, '/v1/chat/completions', payload(), headers)[0], expected)
            self.assertEqual(request(env, '/health', headers={'Host': 'example.org'})[0], 403)
            self.assertEqual(env['adapter'].snapshot()['metrics']['requests'], 0)
            conn = http.client.HTTPConnection('127.0.0.1', env['port'], timeout=2)
            conn.putrequest('GET', '/health', skip_host=True)
            conn.putheader('Host', f'127.0.0.1:{env["port"]}')
            conn.putheader('Host', f'localhost:{env["port"]}')
            conn.endheaders()
            self.assertEqual(conn.getresponse().status, 403); conn.close()
            req = urllib.request.Request(env['url'] + '/v1/chat/completions', method='OPTIONS', headers={
                'Origin': 'null', 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'authorization,content-type'})
            with urllib.request.urlopen(req, timeout=2) as response:
                self.assertEqual(response.status, 204)
                self.assertEqual(response.headers['Access-Control-Allow-Origin'], 'null')
            req.add_header('Access-Control-Request-Headers', 'x-unrecognized')
            with self.assertRaises(urllib.error.HTTPError) as context:
                urllib.request.urlopen(req, timeout=2)
            self.assertEqual(context.exception.code, 403)

    def test_text_only_and_invalid_requests(self):
        with running() as env:
            bad = [dict(payload(), tools=[{'type': 'function'}]), dict(payload(), functions=[{'name': 'anything'}]),
                   dict(payload(), tool_choice='auto'), dict(payload(), model='another-model'), dict(payload(), stream='yes'),
                   {'messages': [{'role': 'tool', 'content': 'tool output'}]},
                   {'messages': [{'role': 'assistant', 'content': 'x', 'tool_calls': [{'id': 'x'}]}]},
                   {'messages': [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAAA'}}]}]},
                   {'messages': [{'role': 'user', 'content': [{'type': 'input_audio', 'input_audio': {'data': 'AAAA'}}]}]},
                   {'messages': [{'role': 'user', 'content': 'bad\x00text'}]}, {'messages': []}, []]
            for value in bad:
                with self.subTest(kind='invalid'):
                    self.assertEqual(request(env, '/v1/chat/completions', value)[0], 400)
            self.assertEqual(request(env, '/v1/chat/completions', payload(), {'Content-Type': 'text/plain'})[0], 415)
            self.assertEqual(request(env, '/v1/chat/completions', raw=b'not-json')[0], 400)
            self.assertEqual(env['adapter'].snapshot()['metrics']['requests'], 0)

    def test_nonstream_and_large_text(self):
        with running() as env:
            value = payload()
            value['messages'][1]['content'] = [{'type': 'text', 'text': '合成' * 45000}]
            code, reply, headers = request(env, '/v1/chat/completions', value)
            self.assertEqual(code, 200)
            self.assertEqual(reply['choices'][0]['message']['content'], 'first message / second message')
            self.assertEqual(reply['choices'][0]['finish_reason'], 'stop')
            self.assertEqual(headers['X-AIRI-Upstream-Streaming'], 'completed-agent-message-events')
            self.assertGreater(len(json.dumps(value).encode('utf-8')), 240000)
            self.assertIsNotNone(env['adapter'].snapshot()['metrics']['last_upstream_first_content_seconds'])
            self.assertEqual(env['adapter'].snapshot()['metrics']['completed'], 1)

    def test_sse_yields_only_after_real_worker_event(self):
        worker = FakeWorker(blocked=True)
        with running(worker) as env:
            conn = http.client.HTTPConnection('127.0.0.1', env['port'], timeout=3)
            conn.request('POST', '/v1/chat/completions', body=json.dumps(payload(True)), headers={'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json', 'Origin': 'null'})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            role = json.loads(response.readline().decode()[5:])
            self.assertEqual(role['choices'][0]['delta'], {'role': 'assistant'})
            self.assertEqual(response.readline(), b'\n')
            arrived = threading.Event(); observed = []
            def read_next():
                line = response.readline()
                observed.append((time.monotonic(), line))
                arrived.set()
            reader = threading.Thread(target=read_next, daemon=True); reader.start()
            time.sleep(.12)
            self.assertFalse(arrived.is_set(), 'role event must not be counted as first generated content')
            worker.release.set()
            self.assertTrue(arrived.wait(2))
            self.assertGreaterEqual(observed[0][0], worker.first_yield_at)
            self.assertIn(b'first message', observed[0][1])
            rest = response.read().decode('utf-8')
            chunks = [json.loads(observed[0][1].decode()[5:])]
            chunks += [json.loads(line[5:]) for line in rest.splitlines() if line.startswith('data: ') and line != 'data: [DONE]']
            content = [chunk['choices'][0]['delta']['content'] for chunk in chunks if 'content' in chunk['choices'][0]['delta']]
            self.assertEqual(content, ['first message', ' / second message'])
            self.assertIn('data: [DONE]', rest)
            conn.close()

    def test_disconnect_cancels_blocked_worker_and_busy(self):
        worker = FakeWorker(blocked=True)
        with running(worker) as env:
            conn = http.client.HTTPConnection('127.0.0.1', env['port'], timeout=3)
            conn.request('POST', '/v1/chat/completions', body=json.dumps(payload(True)), headers={'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json'})
            response = conn.getresponse(); response.readline(); response.readline()
            self.assertTrue(worker.started.wait(1))
            self.assertEqual(request(env, '/v1/chat/completions', payload())[0], 429)
            response.close(); conn.close()
            self.assertTrue(worker.cancelled.wait(2))
            deadline = time.monotonic() + 2
            while env['adapter'].snapshot()['requests_active'] and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertEqual(env['adapter'].snapshot()['requests_active'], 0)
            self.assertEqual(env['adapter'].snapshot()['metrics']['cancelled'], 1)

    def test_error_is_sanitized_and_shutdown_requires_auth(self):
        with running(FakeWorker(failure=True)) as env:
            code, value, _ = request(env, '/v1/chat/completions', payload())
            self.assertEqual(code, 502)
            self.assertNotIn('synthetic-private-error', json.dumps(value))
            self.assertEqual(value['error']['code'], 'UPSTREAM_ERROR')
            self.assertEqual(request(env, '/internal/shutdown', {}, {'Authorization': ''})[0], 401)
            self.assertFalse(env['adapter'].stopping.is_set())
            self.assertEqual(request(env, '/internal/shutdown', {})[0], 200)
            self.assertTrue(env['adapter'].stopping.is_set())

    def test_completed_tool_history_is_projected_without_arguments(self):
        value = payload()
        value['messages'] = [
            {'role': 'user', 'content': 'Earlier synthetic request.'},
            {'role': 'assistant', 'content': 'Original assistant text.', 'tool_calls': [history_call()]},
            {'role': 'tool', 'tool_call_id': 'call_previous', 'content': 'Historical synthetic result.'},
            {'role': 'user', 'content': 'Now chat normally.'},
        ]
        with running() as env:
            self.assertEqual(request(env, '/v1/chat/completions', value)[0], 200)
            projected = env['worker'].last_messages
            rendered = json.dumps(projected, ensure_ascii=False)
            self.assertEqual([item['role'] for item in projected], ['user', 'assistant', 'assistant', 'user'])
            self.assertEqual(projected[1]['content'], 'Original assistant text.')
            self.assertIn('历史工具结果，仅供背景，不执行', rendered)
            self.assertIn('get_weather', rendered)
            self.assertIn('Historical synthetic result.', rendered)
            self.assertNotIn('arguments', rendered)
            self.assertNotIn('never-forward-this-argument', rendered)
            self.assertNotIn('tool_calls', rendered)

    def test_completed_parallel_calls_pair_by_unique_id(self):
        value = payload()
        value['messages'] = [
            {'role': 'assistant', 'content': None, 'tool_calls': [history_call('call_a', 'get_weather'), history_call('call_b', 'image_journal')]},
            {'role': 'tool', 'tool_call_id': 'call_b', 'content': [{'type': 'text', 'text': 'B result'}]},
            {'role': 'tool', 'tool_call_id': 'call_a', 'content': 'A result'},
            {'role': 'user', 'content': 'Next synthetic user message.'},
        ]
        with running() as env:
            self.assertEqual(request(env, '/v1/chat/completions', value)[0], 200)
            projected = env['worker'].last_messages
            self.assertEqual(len(projected), 3)
            self.assertIn('image_journal\n结果：B result', projected[0]['content'])
            self.assertIn('get_weather\n结果：A result', projected[1]['content'])
            self.assertEqual(projected[-1]['role'], 'user')

    def test_incomplete_unmatched_and_unknown_history_still_rejects(self):
        assistant = {'role': 'assistant', 'content': None, 'tool_calls': [history_call()]}
        result = {'role': 'tool', 'tool_call_id': 'call_previous', 'content': 'Completed result.'}
        following_user = {'role': 'user', 'content': 'New user before result.'}
        bad_call = history_call(); bad_call['unexpected'] = 'not-a-known-call-schema'
        bad_name = history_call(); bad_name['function']['name'] = 'bad.name'
        bad_arguments = history_call(); bad_arguments['function']['arguments'] = {'not': 'a string'}
        cases = [
            ([assistant], 'HISTORICAL_TOOL_INCOMPLETE'),
            ([assistant, following_user, result], 'HISTORICAL_TOOL_INCOMPLETE'),
            ([result], 'HISTORICAL_TOOL_UNMATCHED'),
            ([assistant, result, result], 'HISTORICAL_TOOL_UNMATCHED'),
            ([{'role': 'assistant', 'content': None, 'tool_calls': [history_call(), history_call()]}], 'HISTORICAL_TOOL_SCHEMA'),
            ([{'role': 'assistant', 'content': None, 'tool_calls': [bad_call]}], 'HISTORICAL_TOOL_SCHEMA'),
            ([{'role': 'assistant', 'content': None, 'tool_calls': [bad_name]}], 'HISTORICAL_TOOL_SCHEMA'),
            ([{'role': 'assistant', 'content': None, 'tool_calls': [bad_arguments]}], 'HISTORICAL_TOOL_SCHEMA'),
            ([{'role': 'assistant', 'content': None, 'function_call': {'name': 'legacy', 'arguments': '{}'}}], 'LEGACY_FUNCTION_NOT_SUPPORTED'),
            ([{'role': 'assistant', 'content': None, 'tool_calls': [history_call('call_a'), history_call('call_b')]},
              {'role': 'tool', 'tool_call_id': 'call_a', 'content': 'one result'}, following_user], 'HISTORICAL_TOOL_INCOMPLETE'),
        ]
        with running() as env:
            for messages, expected in cases:
                with self.subTest(code=expected):
                    code, reply, _ = request(env, '/v1/chat/completions', {'messages': messages})
                    self.assertEqual(code, 400)
                    self.assertEqual(reply['error']['code'], expected)
                    health = request(env, '/health')[1]
                    self.assertEqual(health['last_error_code'], expected)
                    self.assertEqual(health['metrics']['last_error_code'], expected)
                    self.assertNotIn('never-forward-this-argument', json.dumps(health))
            self.assertEqual(request(env, '/v1/chat/completions', dict(payload(), function_call='none'))[0], 400)
            self.assertEqual(env['adapter'].snapshot()['metrics']['requests'], 0)

    def test_historical_images_are_omitted_but_manual_images_reject(self):
        historical = payload()
        historical['messages'] = [
            {'role': 'assistant', 'content': '', 'tool_calls': [history_call(name='computer_use_read_image')]},
            {'role': 'tool', 'tool_call_id': 'call_previous', 'content': [
                {'type': 'text', 'text': 'Retained historical text.'},
                {'type': 'image_url', 'image_url': {'url': 'file:///synthetic-private-image-url-never-forwarded.png'}},
                {'type': 'input_image', 'image_url': 'data:image/png;base64,synthetic-private-image-bytes-never-forwarded'},
            ]},
            {'role': 'user', 'content': 'Continue without viewing pictures.'},
        ]
        with running() as env:
            self.assertEqual(request(env, '/v1/chat/completions', historical)[0], 200)
            rendered = json.dumps(env['worker'].last_messages, ensure_ascii=False)
            self.assertIn('Retained historical text.', rendered)
            self.assertIn('[历史图片未发送]', rendered)
            self.assertNotIn('synthetic-private-image', rendered)
            self.assertNotIn('file:///', rendered)
            self.assertNotIn('data:image/', rendered)
            for role in ('user', 'assistant'):
                value = {'messages': [{'role': role, 'content': [{'type': 'image_url', 'image_url': {'url': 'file:///still-manual.png'}}]}]}
                self.assertEqual(request(env, '/v1/chat/completions', value)[0], 400)

    def test_worker_error_code_is_whitelisted_without_exception_text(self):
        for code in ['CODEX_PERMISSION_GUARD', 'CODEX_PROTOCOL_ERROR', 'CODEX_TOOLS_DISABLED', 'synthetic-private-error-code', {'unexpected': 'schema'}]:
            with self.subTest(codeKind='whitelisted-or-generic'), running(FakeWorker(failure=True, error_code=code)) as env:
                status, reply, _ = request(env, '/v1/chat/completions', payload())
                expected = code if isinstance(code, str) and code in server.WORKER_ERROR_CODES else 'UPSTREAM_ERROR'
                self.assertEqual(status, 502)
                self.assertEqual(reply['error']['code'], expected)
                health = request(env, '/health')[1]
                self.assertEqual(health['last_error_code'], expected)
                self.assertNotIn('synthetic-private-error', json.dumps(reply) + json.dumps(health))

    def test_token_store_is_local_idempotent_and_not_reported(self):
        with tempfile.TemporaryDirectory(prefix='codex-adapter-token-test-') as directory:
            file = Path(directory) / 'synthetic-token.txt'
            first = server.ensure_token(file)
            self.assertEqual(server.ensure_token(file), first)
            self.assertGreaterEqual(len(first), 32)
            file.write_text('invalid token', encoding='ascii')
            with self.assertRaises(RuntimeError):
                server.ensure_token(file)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(HttpChecks))
    report = {'test': 'codex-chat-http-with-synthetic-worker', 'passed': result.testsRun - len(result.failures) - len(result.errors),
              'total': result.testsRun, 'success': result.wasSuccessful(), 'realCLIOrCloudCalls': False,
              'productionPortStarted': False, 'productionTokenCreatedOrRead': False,
              'streaming': 'completed-agent-message-events', 'tokenStreamingClaimed': False}
    (Path(__file__).parent / 'verification-http.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))
    raise SystemExit(0 if result.wasSuccessful() else 1)
