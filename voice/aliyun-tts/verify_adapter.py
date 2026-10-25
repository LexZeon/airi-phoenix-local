# SPDX-License-Identifier: MIT
"""Offline adapter verification. Never reads a real credential or calls Aliyun."""
from __future__ import annotations

import base64
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
from http.server import ThreadingHTTPServer
from unittest import mock
import wave

ROOT = Path(__file__).resolve().parent


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


configuration = module('verification_aliyun_config', 'aliyun_config.py')
engine = module('verification_aliyun_engine', 'engine.py')
http_server = module('verification_aliyun_http', 'server.py')
FAKE_KEY = 'synthetic_aliyun_key_for_test_20261025'
TOKEN = 'synthetic_local_token_only_for_verification_9949'
PCM = b'\x00\x00\x10\x00' * 2400


def settings(**changes):
    return {**configuration.DEFAULTS, 'apiKey': FAKE_KEY, **changes}


def sse(*events):
    return b''.join(('data: ' + json.dumps(value) + '\n\n').encode('utf-8') for value in events)


def audio_event(data, finish=None):
    return {'output': {'audio': {'data': base64.b64encode(data).decode('ascii')}, 'finish_reason': finish}}


class FakeResponse(io.BytesIO):
    def __init__(self, data, kind='text/event-stream', delay=0):
        super().__init__(data)
        self.headers = {'Content-Type': kind}
        self.delay = delay

    def readline(self, *args):
        if self.delay:
            time.sleep(self.delay)
        return super().readline(*args)


class Opener:
    def __init__(self, response=None, error=None):
        self.response, self.error = response, error
        self.request = None
        self.calls = 0

    def open(self, request, timeout):
        self.request = request
        self.calls += 1
        if self.error:
            raise self.error
        return self.response


class EngineTests(unittest.TestCase):
    def successful(self, cfg=None, data=PCM):
        opener = Opener(FakeResponse(sse(audio_event(data), audio_event(b'', 'stop'))))
        return engine.synthesize('合成验证短句。', cfg or settings(), opener=opener), opener

    def test_simple_supported_payload_and_wav(self):
        result, opener = self.successful()
        request = opener.request
        self.assertEqual(request.full_url, 'https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation')
        body = json.loads(request.data)
        self.assertEqual(body, {'model': 'qwen3-tts-flash', 'input': {'text': '合成验证短句。', 'voice': 'Serena', 'language_type': 'Chinese'}})
        self.assertEqual(request.get_header('X-dashscope-sse'), 'enable')
        self.assertEqual(request.get_header('Authorization'), 'Bearer ' + FAKE_KEY)
        with wave.open(io.BytesIO(result['wav']), 'rb') as wav:
            self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, 24000))
            self.assertEqual(wav.readframes(wav.getnframes()), PCM)
        self.assertAlmostEqual(result['timings']['audioDurationSeconds'], .2)

    def test_region_endpoint(self):
        _, opener = self.successful(settings(region='singapore'))
        self.assertEqual(opener.request.host, 'dashscope-intl.aliyuncs.com')

    def test_chunks_and_timing_are_distinct(self):
        events = sse(audio_event(PCM[:960]), audio_event(PCM[960:]), audio_event(b'', 'stop'))
        opener = Opener(FakeResponse(events, delay=.004))
        result = engine.synthesize('测试。', settings(), opener=opener)
        self.assertGreater(result['timings']['firstAudioMs'], 0)
        self.assertGreater(result['timings']['completeWavMs'], result['timings']['firstAudioMs'] + 5)
        with wave.open(io.BytesIO(result['wav']), 'rb') as wav:
            self.assertEqual(wav.readframes(wav.getnframes()), PCM)

    def test_input_boundary_and_multisentence(self):
        result, _ = self.successful()
        self.assertTrue(result['wav'].startswith(b'RIFF'))
        for text in ('', 'x' * 601, 123, 'a\x00b'):
            opener = Opener(error=AssertionError('network_must_not_run'))
            with self.assertRaises(engine.EngineError) as error:
                engine.synthesize(text, settings(), opener=opener)
            self.assertEqual(error.exception.code, 'INVALID_TEXT')
            self.assertEqual(opener.calls, 0)
        opener = Opener(FakeResponse(sse(audio_event(PCM), audio_event(b'', 'stop'))))
        engine.synthesize('中' * 600, settings(), opener=opener)

    def test_invalid_base64(self):
        opener = Opener(FakeResponse(sse({'output': {'audio': {'data': '%%%'}}}, audio_event(b'', 'stop'))))
        with self.assertRaises(engine.EngineError) as error:
            engine.synthesize('测试。', settings(), opener=opener)
        self.assertEqual(error.exception.code, 'INVALID_AUDIO_DATA')

    def test_no_audio_and_missing_stop(self):
        for events, expected in ((sse(audio_event(b'', 'stop')), 'EMPTY_UPSTREAM_AUDIO'),
                                 (sse(audio_event(PCM)), 'INCOMPLETE_UPSTREAM_AUDIO')):
            with self.assertRaises(engine.EngineError) as error:
                engine.synthesize('测试。', settings(), opener=Opener(FakeResponse(events)))
            self.assertEqual(error.exception.code, expected)

    def test_odd_pcm_rejected(self):
        with self.assertRaises(engine.EngineError) as error:
            self.successful(data=b'\x01')
        self.assertEqual(error.exception.code, 'INVALID_PCM_AUDIO')

    def test_upstream_error_is_sanitized(self):
        raw = {'code': 'InvalidApiKey', 'message': FAKE_KEY + ' arbitrary private upstream detail'}
        candidates = [Opener(FakeResponse(sse(raw))),
                      Opener(FakeResponse(json.dumps(raw).encode(), 'application/json')),
                      Opener(error=urllib.error.HTTPError('https://example.invalid', 401, FAKE_KEY, {}, io.BytesIO(json.dumps(raw).encode())))]
        for opener in candidates:
            with self.assertRaises(engine.EngineError) as error:
                engine.synthesize('测试。', settings(), opener=opener)
            self.assertEqual(error.exception.code, 'ALIYUN_AUTH_FAILED')
            self.assertNotIn(FAKE_KEY, str(error.exception))
            self.assertNotIn('arbitrary', str(error.exception))

    def test_timeout_is_sanitized(self):
        with self.assertRaises(engine.EngineError) as error:
            engine.synthesize('测试。', settings(), opener=Opener(error=TimeoutError(FAKE_KEY)))
        self.assertEqual(error.exception.code, 'ALIYUN_CONNECTION_FAILED')
        self.assertNotIn(FAKE_KEY, str(error.exception))

    def test_cancellation_before_network(self):
        cancelled = threading.Event(); cancelled.set()
        opener = Opener(error=AssertionError('network_must_not_run'))
        with self.assertRaises(engine.EngineError) as error:
            engine.synthesize('测试。', settings(), cancelled, opener=opener)
        self.assertEqual(error.exception.code, 'REQUEST_CANCELLED')
        self.assertEqual(opener.calls, 0)

    def test_arbitrary_host_and_key_header_injection_rejected(self):
        for cfg in (settings(mode='expressive', voice='longanlingxin_v3.1', apiHost='https://attacker.example'),
                    settings(apiKey=FAKE_KEY + '\r\nHeader: value')):
            opener = Opener(error=AssertionError('network_must_not_run'))
            with self.assertRaises(engine.EngineError):
                engine.synthesize('测试。', cfg, opener=opener)
            self.assertEqual(opener.calls, 0)

    def test_redirect_is_not_followed(self):
        with self.assertRaises(engine.EngineError) as error:
            engine.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://attacker.example')
        self.assertEqual(error.exception.code, 'UPSTREAM_REDIRECT_DENIED')

    def test_expressive_wav_validation_and_payload(self):
        wav, _ = engine._pcm_wav(PCM)
        cfg = settings(mode='expressive', voice='longanlingxin_v3.1', apiHost='https://llm-synthetic.cn-beijing.maas.aliyuncs.com')
        result, opener = self.successful(cfg, wav)
        body = json.loads(opener.request.data)
        self.assertEqual(body['input']['format'], 'wav')
        self.assertEqual(body['input']['sample_rate'], 24000)
        self.assertTrue(body['input']['instruction'])
        self.assertEqual(opener.request.full_url, cfg['apiHost'] + '/api/v1/services/audio/tts/SpeechSynthesizer')
        with wave.open(io.BytesIO(result['wav']), 'rb') as check:
            self.assertEqual(check.readframes(check.getnframes()), PCM)
        for invalid in (PCM, wav[:-10], wav + b'trailing bytes'):
            with self.assertRaises(engine.EngineError):
                self.successful(cfg, invalid)

    def test_expressive_multiple_complete_wav_sentences(self):
        first, _ = engine._pcm_wav(PCM[:960])
        second, _ = engine._pcm_wav(PCM[960:])
        result, _ = self.successful(settings(mode='expressive', voice='longanlingxin_v3.1',
            apiHost='https://llm-synthetic.ap-southeast-1.maas.aliyuncs.com', region='singapore'), first + second)
        with wave.open(io.BytesIO(result['wav']), 'rb') as wav:
            self.assertEqual(wav.readframes(wav.getnframes()), PCM)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='airi-aliyun-test-')
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_public_default_has_no_secret_or_side_effect(self):
        result = configuration.get_public_settings(self.root)
        self.assertEqual(result['voice'], 'Serena')
        self.assertFalse(result['configured'])
        self.assertNotIn('apiKey', result)
        self.assertNotIn('protectedKey', result)
        self.assertFalse((self.root / 'private').exists())

    @unittest.skipUnless(os.name == 'nt', 'Actual current-user DPAPI only on Windows')
    def test_actual_dpapi_round_trip_and_redaction(self):
        saved = configuration.save_settings({'apiKey': FAKE_KEY}, self.root)
        self.assertTrue(saved['configured'])
        self.assertNotIn(FAKE_KEY, json.dumps(saved))
        raw = (self.root / 'private/settings.json').read_text(encoding='utf-8')
        self.assertNotIn(FAKE_KEY, raw)
        self.assertEqual(configuration.load_private_settings(self.root)['apiKey'], FAKE_KEY)
        configuration.save_settings({'voice': 'Maia', 'apiKey': ''}, self.root)
        self.assertEqual(configuration.load_private_settings(self.root)['apiKey'], FAKE_KEY)
        configuration.save_settings({'clearKey': True}, self.root)
        self.assertFalse(configuration.get_public_settings(self.root)['keyConfigured'])
        with self.assertRaises(configuration.ConfigError):
            configuration.load_private_settings(self.root)

    def test_host_region_and_voice_validation(self):
        for payload in ({'region': 'unknown'}, {'mode': 'unknown'}, {'voice': 'not-a-voice'},
                        {'apiHost': 'https://user:secret@llm-valid.cn-beijing.maas.aliyuncs.com'},
                        {'apiHost': 'https://llm-valid.cn-beijing.maas.aliyuncs.com/path'},
                        {'apiHost': 'https://llm-valid.cn-beijing.maas.aliyuncs.com?key=value'},
                        {'apiHost': 'https://llm-valid.cn-beijing.maas.aliyuncs.com:444'},
                        {'region': 'singapore', 'apiHost': 'https://llm-valid.cn-beijing.maas.aliyuncs.com'},
                        {'instruction': 'x' * 301}, {'apiKey': 'too-short'}, {'unknown': 'value'}):
            with self.assertRaises(configuration.ConfigError):
                configuration.save_settings(payload, self.root)
        result = configuration.save_settings({'mode': 'expressive', 'region': 'singapore',
             'apiHost': 'llm-synthetic.ap-southeast-1.maas.aliyuncs.com'}, self.root)
        self.assertEqual(result['voice'], 'longanlingxin_v3.1')
        self.assertNotIn('anruorou_v3.1', {value['id'] for value in result['voices']})
        self.assertFalse(result['configured'])

    def test_test_record_does_not_keep_text_or_stale_result(self):
        saved = configuration.save_settings({}, self.root)
        revision = saved['revision']
        result = {'status': 'passed', 'timings': {'firstAudioMs': 2, 'completeWavMs': 5, 'audioDurationSeconds': .2},
                  'wav': b'synthetic', 'apiKey': FAKE_KEY, 'text': 'synthetic transcript not retained'}
        self.assertTrue(configuration.record_test(result, self.root, expected_revision=revision))
        report = configuration.get_public_settings(self.root)['lastTest']
        self.assertEqual(set(report), {'status', 'checkedAt', 'timings'})
        self.assertEqual(report['status'], 'success')
        configuration.save_settings({'voice': 'Maia'}, self.root)
        self.assertFalse(configuration.record_test(result, self.root, expectedRevision=revision))
        self.assertIsNone(configuration.get_public_settings(self.root)['lastTest'])

    def test_token_is_atomic_and_stable(self):
        target = self.root / 'local-token.txt'
        output = []
        threads = [threading.Thread(target=lambda: output.append(configuration.ensure_token(target))) for _ in range(5)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(set(output)), 1)
        self.assertEqual(len(output[0]), 43)
        self.assertEqual(configuration.ensure_token(target), output[0])

    def test_public_test_metadata_is_whitelisted(self):
        configuration.save_settings({}, self.root)
        path = self.root / 'private/settings.json'
        value = json.loads(path.read_text(encoding='utf-8'))
        value['lastTest'] = {'status': 'success', 'checkedAt': '2026-10-25T10:00:00+00:00',
                            'timings': {'firstAudioMs': 1, 'completeWavMs': 2, 'audioDurationSeconds': .2},
                            'apiKey': FAKE_KEY, 'arbitraryPrivateText': 'not-public'}
        path.write_text(json.dumps(value), encoding='utf-8')
        public = configuration.get_public_settings(self.root)
        self.assertNotIn(FAKE_KEY, json.dumps(public))
        self.assertNotIn('arbitraryPrivateText', public['lastTest'])
        value['lastTest'] = None
        value['revision'] = FAKE_KEY
        path.write_text(json.dumps(value), encoding='utf-8')
        public = configuration.get_public_settings(self.root)
        self.assertIsNone(public['lastTest'])
        self.assertIsNone(public['revision'])


class FakeConfig:
    ConfigError = configuration.ConfigError
    @staticmethod
    def get_public_settings():
        return {'configured': True, 'keyConfigured': True, 'voice': 'Serena'}
    @staticmethod
    def load_private_settings():
        return settings()


class FakeEngine:
    EngineError = engine.EngineError
    calls = 0
    hold = False
    @classmethod
    def synthesize(cls, text, config, cancelled):
        cls.calls += 1
        if cls.hold:
            while not cancelled.wait(.01):
                pass
            raise cls.EngineError('REQUEST_CANCELLED', '语音请求已取消。', 499)
        data, duration = engine._pcm_wav(PCM)
        return {'wav': data, 'timings': {'firstAudioMs': 1, 'completeWavMs': 2, 'audioDurationSeconds': duration}}


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter = http_server.Adapter(FakeConfig, FakeEngine)
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), http_server.make_handler(cls.adapter, TOKEN, 'f' * 32, 0))
        cls.port = cls.server.server_port
        cls.server.RequestHandlerClass = http_server.make_handler(cls.adapter, TOKEN, 'f' * 32, cls.port)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.adapter.close(); cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=2)

    def request(self, path='/v1/audio/speech', payload=None, token=TOKEN, host=None, origin='null', method='POST'):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=4)
        headers = {'Host': host or f'127.0.0.1:{self.port}', 'Content-Type': 'application/json'}
        if origin is not None: headers['Origin'] = origin
        if token is not None: headers['Authorization'] = 'Bearer ' + token
        body = json.dumps(payload if payload is not None else {'model': 'aliyun-qwen-tts', 'input': '验证。', 'voice': 'configured', 'response_format': 'wav'}) if method == 'POST' else None
        connection.request(method, path, body, headers)
        response = connection.getresponse()
        data = response.read()
        result = (response.status, dict(response.getheaders()), data)
        connection.close()
        return result

    def test_authentication_and_origin(self):
        initial = FakeEngine.calls
        for kwargs in ({'token': None}, {'token': 'bad-token'}, {'host': 'attacker.example'}, {'origin': 'https://attacker.example'}):
            status, _, body = self.request(**kwargs)
            self.assertIn(status, (401, 403))
            self.assertNotIn(FAKE_KEY.encode(), body)
        self.assertEqual(FakeEngine.calls, initial)

    def test_health_and_model_metadata_redacted(self):
        status, _, body = self.request('/health', method='GET', token=None)
        self.assertEqual(status, 200)
        value = json.loads(body)
        self.assertEqual(value['service'], 'airi-aliyun-tts')
        self.assertTrue(value['configured'])
        self.assertFalse(value['actual_airi_playback_latency_measured'])
        self.assertNotIn(FAKE_KEY.encode(), body)
        self.assertNotIn(TOKEN.encode(), body)
        for path in ('/v1/models', '/v1/audio/voices'):
            self.assertEqual(self.request(path, method='GET')[0], 200)

    def test_non_ascii_authorization_is_rejected_without_handler_exception(self):
        self.assertEqual(self.request(token='invalid_\xe9_header')[0], 401)

    def test_http_wav_and_format_bounds(self):
        status, headers, body = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'audio/wav')
        with wave.open(io.BytesIO(body), 'rb') as wav:
            self.assertEqual(wav.readframes(wav.getnframes()), PCM)
        for value in ({'input': 'x' * 601}, {'input': 'x', 'response_format': 'mp3'},
                      {'input': 'x', 'model': 'foreign'}, {'input': 'x', 'speed': 1.1},
                      {'input': 'x', 'voice': 'arbitrary'}):
            self.assertEqual(self.request(payload=value)[0], 400)

    def test_concurrency_is_bounded_and_cancellable(self):
        FakeEngine.hold = True
        try:
            first = self.adapter.begin('第一句', 'configured')
            second = self.adapter.begin('第二句', 'configured')
            with self.assertRaises(http_server.RequestError) as error:
                self.adapter.begin('第三句', 'configured')
            self.assertEqual(error.exception.status, 429)
            first['cancelled'].set(); second['cancelled'].set()
            self.assertTrue(first['finished'].wait(2)); self.assertTrue(second['finished'].wait(2))
        finally:
            FakeEngine.hold = False


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromModule(__import__(__name__))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    report = {'test': 'aliyun-tts-offline-adapter', 'testsRun': result.testsRun,
              'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped),
              'passed': result.wasSuccessful(), 'actualCurrentUserDpapiTested': os.name == 'nt',
              'realCloudRequests': 0, 'realCredentialsRead': False,
              'scope': 'Temporary fixtures, fake SSE/HTTP engine and synthetic DPAPI credential only; not a cloud latency or AIRI playback benchmark.'}
    (ROOT / 'verification-adapter.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))
    raise SystemExit(0 if result.wasSuccessful() else 1)
