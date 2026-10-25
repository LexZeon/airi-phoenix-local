"""Published online-selection fixture. Never reads real AIRI settings or starts a service."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

checks = []
def check(name, value):
    assert value, name
    checks.append(name)

with tempfile.TemporaryDirectory(prefix='airi-online-choice-public-') as directory:
    base = Path(directory)
    adapter = base / 'runtime/airi-codex-chat'
    adapter.mkdir(parents=True)
    source = Path(__file__).resolve().parents[1] / 'online-chat/server.py'
    shutil.copyfile(source, adapter / 'server.py')
    settings = base / 'synthetic-settings.json'
    settings.write_text('{}', encoding='utf-8')
    before = hashlib.sha256(settings.read_bytes()).hexdigest()
    roots = {
        'AIRI_COMPANIONS_ROOT': str(base), 'AIRI_CONTROL_DATA_DIR': str(base / 'state'),
        'AIRI_OFFLINE_SETTINGS': str(settings), 'AIRI_MODELS_ROOT': str(base / 'models'),
        'AIRI_WORKBENCH': str(base / 'workbench'), 'AIRI_SPEECH_ROOT': str(base / 'speech'),
        'AIRI_TTS_ROOT': str(base / 'tts'), 'AIRI_SAPI_ROOT': str(base / 'sapi'),
        'AIRI_CODEX_CHAT_ROOT': str(adapter),
    }
    previous = {name: os.environ.get(name) for name in roots}
    os.environ.update(roots)
    try:
        import profiles
        from airi_catalog import catalog
        check('default-remains-local-9b', profiles.DEFAULT['chat'] == 'qwen9')
        check('online-choice-text-chat-only', profiles.CHOICES['codex-chatgpt'][0] == 'chat' and '9948' in profiles.CHOICES['codex-chatgpt'][1])
        online = next(item for item in catalog()['items'] if item['id'] == 'codex-chatgpt')
        check('online-marked-and-no-images-tools', online['online'] and not online['capabilities']['images'] and not online['capabilities']['tools'])
        check('complete-answer-streaming-disclosed', online['capabilities']['tokenStreaming'] is False and online['latency']['samples'] == 1)
        choice = {'selections': dict(profiles.DEFAULT), 'custom': {}}
        choice['selections'].update(chat='codex-chatgpt', tts='sapi-huihui')
        normalized = profiles.normalize(choice)
        endpoint = profiles.endpoint(normalized, 'chat')
        check('loopback-token-generated-only-in-fixture', endpoint['apiKey'] not in ('local', '') and (adapter / 'api-token.txt').is_file())
        check('public-selection-does-not-expose-token', endpoint['apiKey'] not in json.dumps(profiles.public_profile(normalized)))
        check('vision-local-and-voice-preserved', normalized['selections']['vision'] == 'vision9' and normalized['selections']['tts'] == 'sapi-huihui')
        wrong = {'selections': dict(profiles.DEFAULT), 'custom': {}}
        wrong['selections']['vision'] = 'codex-chatgpt'
        try:
            profiles.normalize(wrong)
        except ValueError:
            checks.append('online-cannot-be-vision-choice')
        else:
            raise AssertionError('online accepted as vision')
        check('isolated-settings-file-unchanged', before == hashlib.sha256(settings.read_bytes()).hexdigest())
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

report = {'test': 'published-online-choice-isolated-fixture', 'passed': len(checks), 'checks': checks,
          'realSettingsReadOrChanged': False, 'servicesStarted': False, 'credentialsRead': False}
(Path(__file__).parent / 'verification-online-choice.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report))
