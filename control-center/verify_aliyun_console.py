"""Isolated Aliyun console checks. Synthetic credentials/audio; no cloud requests.

All private configuration, profile settings and samples are held in temporary
directories. These checks establish protocol/UI boundaries, not real synthesis
quality, cloud latency or microphone-to-speaker behavior.
"""
from __future__ import annotations

import contextlib
import datetime
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.request
import wave
from unittest.mock import patch

from aliyun_bridge import AliyunTtsBridge

CONTROL = Path(__file__).resolve().parent
RUNTIME = CONTROL.parent / 'voice' / 'aliyun-tts'
SYNTHETIC_KEY = 'sk-synthetic_aliyun_console_credential_123456789'


def wav_fixture():
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b'\x00\x00' * 2400)
    return stream.getvalue()


def source_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Fixture(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='airi-aliyun-console-')
        self.root = Path(self.directory.name)
        self.control = self.root / 'control-center'
        self.runtime = self.root / 'runtime' / 'airi-aliyun-tts'
        self.control.mkdir()
        self.runtime.mkdir(parents=True)
        # Establish isolated deployment paths before importing profiles/server:
        # their module-level state must not read the user's saved preferences.
        self.environment = patch.dict(os.environ, {
            'AIRI_COMPANIONS_ROOT': str(self.root),
            'AIRI_CONTROL_DATA_DIR': str(self.control / 'state'),
            'AIRI_OFFLINE_SETTINGS': str(self.root / 'runtime' / 'airi-offline' / 'offline-settings.json'),
            'AIRI_CONTROL_PORT': '9944',
            'AIRI_MODELS_ROOT': str(self.root / 'synthetic-models'),
            'AIRI_WORKBENCH': str(self.root / 'synthetic-workbench'),
            'AIRI_SPEECH_ROOT': str(self.root / 'runtime' / 'airi-speech'),
            'AIRI_TTS_ROOT': str(self.root / 'runtime' / 'airi-qwen-tts'),
            'AIRI_SAPI_ROOT': str(self.root / 'runtime' / 'airi-sapi'),
            'AIRI_CODEX_CHAT_ROOT': str(self.root / 'runtime' / 'airi-codex-chat'),
            'AIRI_CODEX_WORKSPACE': str(self.root / 'synthetic-codex-workspace'),
            'AIRI_ALIYUN_TTS_ROOT': str(self.runtime),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        shutil.copyfile(RUNTIME / 'aliyun_config.py', self.runtime / 'aliyun_config.py')
        self.config = source_module(self.runtime / 'aliyun_config.py', 'aliyun_console_fixture_config')
        self.calls = 0
        self.audio = wav_fixture()
        self.engine = types.SimpleNamespace(test_synthesis=self.synthesize)
        self.bridge = AliyunTtsBridge(self.control, self.config, self.engine)
        self.settings = self.root / 'runtime' / 'airi-offline' / 'offline-settings.json'
        self.settings.parent.mkdir()
        self.profile = {'selections': {'chat': 'qwen9', 'vision': 'vision9', 'asr': 'sensevoice', 'tts': 'sapi-huihui'}, 'custom': {}}
        self.settings.write_text(json.dumps({'screen': {'enabled': False}, 'controlCenterSelection': self.profile,
                                            'revision': 'synthetic-before-save'}), encoding='utf-8')
        self.preferences = self.control / 'state' / 'preferences.json'
        self.preferences.parent.mkdir()
        self.preferences.write_text(json.dumps({'profile': self.profile}), encoding='utf-8')
        self.before_settings = self.settings.read_bytes()
        self.before_preferences = self.preferences.read_bytes()

    def tearDown(self):
        self.directory.cleanup()

    def save_key(self, **fields):
        return self.bridge.save({'apiKey': SYNTHETIC_KEY, **fields})

    def synthesize(self):
        self.calls += 1
        private = self.config.load_private_settings(root=self.runtime)
        self.assertEqual(private['apiKey'], SYNTHETIC_KEY)
        return {'wav': self.audio, 'text': '固定中文测试句。', 'model': 'qwen3-tts-flash',
                'voice': private['voice'], 'configRevision': private['revision'],
                'timings': {'firstAudioMs': 12.5, 'completeWavMs': 31.25, 'audioDurationSeconds': .1,
                            'privateVendorDebug': SYNTHETIC_KEY},
                'privateVendorDebug': SYNTHETIC_KEY}

    def assert_no_secret(self, value):
        serialized = json.dumps(value, ensure_ascii=False)
        self.assertNotIn(SYNTHETIC_KEY, serialized)
        self.assertNotIn(SYNTHETIC_KEY[:15], serialized)
        self.assertNotIn('protectedKey', serialized)
        self.assertNotIn('privateVendorDebug', serialized)

    def assert_settings_preserved(self):
        self.assertEqual(self.before_settings, self.settings.read_bytes())
        self.assertEqual(self.before_preferences, self.preferences.read_bytes())

    @contextlib.contextmanager
    def temporary_http(self):
        import server
        import profiles
        import airi_catalog
        from http.server import ThreadingHTTPServer
        logs = self.control / 'logs'
        logs.mkdir(exist_ok=True)
        requests = self.control / 'state' / 'requests'
        requests.mkdir(exist_ok=True)
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        port = httpd.server_address[1]
        origin = f'http://127.0.0.1:{port}'
        def forbidden(*args, **kwargs):
            raise AssertionError('This fixture must not launch processes or make model requests.')
        replacements = {
            server: {'PORT': port, 'ORIGIN': origin, 'TOKEN': 'fixture-csrf-token', 'ROOT': self.control,
                     'BASE': self.root, 'STATE': self.control / 'state', 'LOGS': logs,
                     'SETTINGS': self.settings, 'PREFERENCES': self.preferences, 'REQUESTS': requests,
                     'ALIYUN': self.bridge, 'STATUS': {'checkedAt': None, 'services': []},
                     'launch_job': forbidden, 'apply_profile': forbidden, 'request_json': forbidden},
            profiles: {'ROOT': self.control, 'BASE': self.root, 'DATA_ROOT': self.control / 'state', 'SETTINGS': self.settings,
                       'PREFERENCES': self.preferences, 'REQUESTS': requests},
            airi_catalog: {'BASE': self.root, 'MODELS': self.root / 'synthetic-models',
                           'SPEECH': self.root / 'runtime' / 'airi-speech',
                           'QWEN': self.root / 'runtime' / 'airi-qwen-tts',
                           'SAPI': self.root / 'runtime' / 'airi-sapi',
                           'CODEX_CHAT': self.root / 'runtime' / 'airi-codex-chat',
                           'ALIYUN_TTS': self.runtime, 'discover_codex': lambda: None,
                           'AliyunTtsBridge': lambda root: self.bridge},
        }
        with contextlib.ExitStack() as stack:
            for module, values in replacements.items():
                for name, value in values.items():
                    stack.enter_context(patch.object(module, name, value))
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def request(route, body=None, extra=None):
                headers = {'Origin': origin, 'X-Control-CSRF': server.TOKEN, 'Content-Type': 'application/json'}
                headers.update(extra or {})
                call = urllib.request.Request(origin + route,
                    data=json.dumps(body).encode('utf-8') if body is not None else None, headers=headers)
                try:
                    response = opener.open(call, timeout=5)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    raw = response.read()
                    mime = response.headers.get_content_type()
                    value = json.loads(raw) if mime == 'application/json' else raw
                    return response.status, value, mime
            try:
                yield request
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=3)


class BridgeChecks(Fixture):
    def test_public_configuration_without_key_is_visible_and_inactive(self):
        public = self.bridge.status()
        self.assertTrue(public['available'])
        self.assertFalse(public['configured'])
        self.assertFalse(public['keyConfigured'])
        self.assertEqual(public['voice'], 'Serena')
        self.assertFalse(public['streamingPlayback'])
        self.assert_no_secret(public)
        with self.assertRaises(ValueError):
            self.bridge.test()
        self.assertEqual(self.calls, 0)
        self.assert_settings_preserved()

    def test_save_uses_private_storage_and_preserves_current_profile(self):
        public = self.save_key()
        self.assertTrue(public['keyConfigured'])
        self.assertTrue(public['configured'])
        self.assert_no_secret(public)
        stored = (self.runtime / 'private' / 'settings.json').read_text(encoding='utf-8')
        self.assertNotIn(SYNTHETIC_KEY, stored)
        self.assertNotIn(SYNTHETIC_KEY[:15], stored)
        self.assert_settings_preserved()
        self.assertEqual(self.calls, 0)

    def test_fixed_preview_returns_only_validated_wav_and_timings(self):
        self.save_key()
        result = self.bridge.test()
        self.assertTrue(result['ok'])
        self.assertEqual(self.calls, 1)
        self.assertEqual(result['sampleUrl'], '/api/aliyun/sample.wav')
        self.assertEqual(self.bridge.sample_audio(), self.audio)
        self.assertEqual(set(result['test']['timings']), {'firstAudioMs', 'completeWavMs', 'audioDurationSeconds'})
        self.assertFalse(self.bridge.status()['streamingPlayback'])
        self.assert_no_secret(result)
        self.assert_no_secret(self.bridge.status())
        self.assert_settings_preserved()

    def test_failure_hides_vendor_details_and_removes_stale_sample(self):
        self.save_key()
        self.bridge.test()
        def fail():
            raise RuntimeError('vendor payload ' + SYNTHETIC_KEY)
        self.engine.test_synthesis = fail
        with self.assertRaises(ValueError) as raised:
            self.bridge.test()
        self.assertNotIn(SYNTHETIC_KEY, str(raised.exception))
        status = self.bridge.status()
        self.assertFalse(status['sampleAvailable'])
        self.assertEqual(status['lastTest']['status'], 'failed')
        self.assert_no_secret(status)

    def test_configuration_revision_change_rejects_stale_preview(self):
        self.save_key()
        def changed_during_test():
            result = self.synthesize()
            self.config.save_settings({'voice': 'Maia'}, root=self.runtime)
            return result
        self.engine.test_synthesis = changed_during_test
        with self.assertRaises(ValueError):
            self.bridge.test()
        self.assertFalse(self.bridge.status()['sampleAvailable'])
        with self.assertRaises(ValueError):
            self.bridge.sample_audio()

    def test_preview_lock_rejects_duplicate_work(self):
        self.save_key()
        self.bridge.test_lock.acquire()
        try:
            with self.assertRaises(ValueError):
                self.bridge.test()
            self.assertEqual(self.calls, 0)
        finally:
            self.bridge.test_lock.release()

    def test_invalid_audio_and_nonfinite_timings_are_rejected(self):
        self.save_key()
        for invalid in ({'wav': b'not-wave', 'timings': {}},
                        {'wav': self.audio, 'timings': {'firstAudioMs': float('nan'), 'completeWavMs': 1, 'audioDurationSeconds': .1}}):
            with self.subTest(invalid='audio' if invalid['wav'] != self.audio else 'timings'):
                self.engine.test_synthesis = lambda value=invalid: value
                with self.assertRaises(ValueError):
                    self.bridge.test()
                self.assertFalse(self.bridge.status()['sampleAvailable'])


class HttpChecks(Fixture):
    def test_missing_key_still_appears_in_catalog_and_bootstrap(self):
        with self.temporary_http() as request:
            status, data, _ = request('/api/catalog')
            self.assertEqual(status, 200)
            choice = next(item for item in data['items'] if item['id'] == 'aliyun-tts')
            self.assertTrue(choice['online'])
            self.assertFalse(choice['configured'])
            self.assertFalse(choice['cloudTested'])
            self.assertEqual(choice['evidence'], [])
            self.assertFalse(choice['capabilities']['streamingPlayback'])
            status, bootstrap, _ = request('/api/bootstrap')
            self.assertEqual(status, 200)
            self.assertEqual(bootstrap['applied']['selections']['tts'], 'sapi-huihui')
            self.assert_no_secret(bootstrap)
            self.assertEqual(request('/api/aliyun/test', {})[0], 400)
        self.assertEqual(self.calls, 0)
        self.assert_settings_preserved()

    def test_save_and_test_use_only_isolated_configuration_and_fixed_audio(self):
        with self.temporary_http() as request:
            status, data, _ = request('/api/aliyun/config', {'apiKey': SYNTHETIC_KEY})
            self.assertEqual(status, 200)
            self.assertTrue(data['config']['configured'])
            self.assert_no_secret(data)
            self.assert_settings_preserved()
            self.assertEqual(self.calls, 0)
            status, data, _ = request('/api/aliyun/test', {})
            self.assertEqual(status, 200)
            self.assert_no_secret(data)
            self.assertEqual(self.calls, 1)
            code, audio, mime = request('/api/aliyun/sample.wav')
            self.assertEqual((code, mime), (200, 'audio/wav'))
            self.assertEqual(audio, self.audio)
            for route in ('/api/aliyun/config', '/api/bootstrap', '/api/catalog'):
                self.assert_no_secret(request(route)[1])
        self.assert_settings_preserved()

    def test_host_origin_and_csrf_reject_before_configuration_or_synthesis(self):
        with self.temporary_http() as request:
            for extra in ({'Host': 'example.org'}, {'Origin': 'https://example.org'},
                          {'X-Control-CSRF': ''}, {'Sec-Fetch-Site': 'cross-site'}):
                with self.subTest(header=next(iter(extra))):
                    self.assertEqual(request('/api/aliyun/config', {'apiKey': SYNTHETIC_KEY}, extra)[0], 403)
                    self.assertEqual(request('/api/aliyun/test', {}, extra)[0], 403)
            self.assertFalse((self.runtime / 'private' / 'settings.json').exists())
            self.assertEqual(request('/api/aliyun/config', extra={'Host': 'example.org'})[0], 403)
        self.assertEqual(self.calls, 0)
        self.assert_settings_preserved()

    def test_preview_rejects_arbitrary_text_and_sample_path_traversal(self):
        with self.temporary_http() as request:
            request('/api/aliyun/config', {'apiKey': SYNTHETIC_KEY})
            for body in ({'text': 'Do not send this arbitrary text.'}, {'file': '../../private/settings.json'}):
                self.assertEqual(request('/api/aliyun/test', body)[0], 400)
            self.assertEqual(self.calls, 0)
            self.assertEqual(request('/api/aliyun/sample.wav')[0], 404)
            request('/api/aliyun/test', {})
            for route in ('/api/aliyun/sample.wav?path=../../private/settings.json',
                          '/api/aliyun/sample.wav?file=anything', '/api/aliyun/../../private/settings.json',
                          '/api/aliyun/sample.wav/../../private/settings.json'):
                with self.subTest(route=route):
                    code, value, _ = request(route)
                    self.assertIn(code, (400, 404))
                    self.assert_no_secret(value)

    def test_http_cloud_failure_is_sanitized_and_does_not_change_model_selection(self):
        with self.temporary_http() as request:
            request('/api/aliyun/config', {'apiKey': SYNTHETIC_KEY})
            def fail():
                raise RuntimeError('vendor response ' + SYNTHETIC_KEY)
            self.engine.test_synthesis = fail
            code, error, _ = request('/api/aliyun/test', {})
            self.assertEqual(code, 400)
            self.assert_no_secret(error)
            self.assert_no_secret(request('/api/aliyun/config')[1])
            self.assertEqual(request('/api/bootstrap')[1]['applied']['selections']['tts'], 'sapi-huihui')
        self.assert_settings_preserved()


class ProfileChecks(Fixture):
    def test_profile_uses_local_token_and_tracks_dynamic_voice(self):
        import profiles
        with patch.object(profiles, 'BASE', self.root), patch.object(profiles, 'ROOT', self.control), \
                patch.object(profiles, 'SETTINGS', self.settings), patch.object(profiles, 'PREFERENCES', self.preferences), \
                patch.object(profiles, 'DATA_ROOT', self.control / 'state'):
            profile = json.loads(json.dumps(self.profile))
            profile['selections']['tts'] = 'aliyun-tts'
            selected = profiles.normalize(profile)
            with self.assertRaises(ValueError):
                profiles.endpoint(selected, 'tts')
            self.save_key()
            with self.assertRaises(ValueError):
                profiles.endpoint(selected, 'tts')
            self.bridge.test()
            endpoint = profiles.endpoint(selected, 'tts')
            self.assertEqual(endpoint['baseUrl'], 'http://127.0.0.1:9949/v1/')
            self.assertEqual(endpoint['model'], 'aliyun-qwen-tts')
            self.assertEqual(endpoint['voice'], 'configured')
            self.assertEqual(self.bridge.status()['voice'], 'Serena')
            self.assertNotEqual(endpoint['apiKey'], SYNTHETIC_KEY)
            self.assertEqual(endpoint['apiKey'], (self.runtime / 'api-token.txt').read_text().strip())
            self.assert_no_secret(profiles.public_profile(selected))
            self.assertEqual(profiles.current_profile()['selections']['tts'], 'sapi-huihui')
            self.bridge.save({'voice': 'Maia'})
            self.bridge.test()
            self.assertEqual(profiles.endpoint(selected, 'tts')['voice'], 'configured')
            self.assertEqual(self.bridge.status()['voice'], 'Maia')
            result = profiles.apply_profile(selected, settings_path=self.settings)
            self.assertTrue(result['ok'])
            written = json.loads(self.settings.read_text(encoding='utf-8'))
            provider = written['providers']['control-center-speech']['config']
            self.assertEqual(provider['voice'], 'configured')
            self.assertEqual(provider['apiKey'], endpoint['apiKey'])
            self.assertNotIn(SYNTHETIC_KEY, self.settings.read_text(encoding='utf-8'))
            written.pop('controlCenterSelection')
            self.settings.write_text(json.dumps(written), encoding='utf-8')
            self.assertEqual(profiles.current_profile()['selections']['tts'], 'aliyun-tts')
            self.assertEqual(profiles.current_profile()['selections']['chat'], 'qwen9')


class UiSemanticsChecks(unittest.TestCase):
    def test_online_voice_actions_and_disclosure_are_distinct_from_chat(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node is needed for the isolated render function fixture.')
        source = (CONTROL / 'web' / 'app.js').read_text(encoding='utf-8')
        script = r'''
const fs=require('fs'),vm=require('vm');
const source=fs.readFileSync(0,'utf8');
const match=source.match(/function renderModules\(\)\{[\s\S]*?(?=\nfunction renderResources\()/);
if(!match)throw Error('Cannot isolate renderModules');
const grid={innerHTML:''};
const draft={selections:{tts:'aliyun-tts',chat:'codex-chatgpt'},custom:{}};
const catalog={items:[{id:'aliyun-tts',module:'tts',name:'Aliyun',online:true},
                     {id:'codex-chatgpt',module:'chat',name:'ChatGPT',online:true}]};
const sandbox={modules:[{id:'tts',name:'Voice',icon:'',note:''},{id:'chat',name:'Chat',icon:'',note:''}],
  draft,catalog,$:()=>grid,escapeHtml:value=>String(value??''),
  selected:module=>catalog.items.find(item=>item.id===draft.selections[module]),
  document:{querySelectorAll:()=>[]},window:{},updateModuleStates:()=>{}};
vm.runInNewContext(match[0]+'\nrenderModules();',sandbox,{timeout:1000});
const card=id=>grid.innerHTML.match(new RegExp('<article class="module-card" id="'+id+'">([\\s\\S]*?)</article>'))?.[1];
const tts=card('tts'),chat=card('chat');
if(!tts||!chat)throw Error('Expected both rendered cards');
if(!tts.includes('data-aliyun-settings')||!tts.includes('data-offline-sapi'))throw Error('Missing voice controls');
if(tts.includes('data-offline-nine')||tts.includes('ChatGPT')||tts.includes('9B'))throw Error('Chat fallback leaked into voice card');
if(!chat.includes('data-offline-nine')||!chat.includes('ChatGPT'))throw Error('Chat controls regressed');
if(!tts.includes('完整小句')||!tts.includes('按量付费'))throw Error('Missing playback/billing scope');
process.stdout.write('render-voice-and-chat-boundaries-ok');
'''
        result = subprocess.run([node, '-e', script], input=source, text=True, encoding='utf-8',
                                capture_output=True, timeout=5, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'render-voice-and-chat-boundaries-ok')
        html = (CONTROL / 'web' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('id="aliyun-key" type="password"', html)
        self.assertIn('/aliyun-tts.js', html)
        self.assertIn('/aliyun-tts.css', html)


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    report = {'test': 'aliyun-console-isolated-dpapi-and-loopback-http-fixtures',
              'testedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'passed': result.testsRun - len(result.failures) - len(result.errors), 'total': result.testsRun,
              'success': result.wasSuccessful(), 'realCloudRequests': 0, 'realCredentialsRead': False,
              'realSettingsChanged': False, 'servicesStarted': False, 'productionServerRestarted': False,
              'temporaryLoopbackHttpServer': True,
              'scope': 'Synthetic protocol/UI boundaries; not cloud speed, voice quality or actual AIRI playback.'}
    report['sourceSha256'] = {name: hashlib.sha256((CONTROL / name).read_bytes()).hexdigest()
                             for name in ('aliyun_bridge.py', 'server.py', 'profiles.py', 'airi_catalog.py',
                                          'web/app.js', 'web/index.html', 'web/aliyun-tts.js', 'web/aliyun-tts.css')}
    report['runtimeConfigSourceSha256'] = hashlib.sha256((RUNTIME / 'aliyun_config.py').read_bytes()).hexdigest()
    (CONTROL / 'verification-aliyun-console.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))
    raise SystemExit(0 if result.wasSuccessful() else 1)
