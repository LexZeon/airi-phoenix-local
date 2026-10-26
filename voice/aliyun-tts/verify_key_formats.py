# SPDX-License-Identifier: MIT
"""Isolated key-format regression checks; synthetic credentials and no network.

No real private directory is read or written. Windows DPAPI is exercised only
with clearly synthetic values in a TemporaryDirectory. No key is printed.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import socket
import tempfile
from unittest import mock

SOURCE = Path(__file__).resolve().parent


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, SOURCE / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def run():
    passed = 0
    failed = []

    def check(name, action):
        nonlocal passed
        try:
            if action() is not True:
                raise AssertionError()
            passed += 1
        except Exception:
            # Exception payloads and request objects are deliberately omitted.
            failed.append(name)

    configuration = module('isolated_aliyun_key_formats_config', 'aliyun_config.py')
    engine = module('isolated_aliyun_key_formats_engine', 'engine.py')
    accepted = {
        'legacy': 'sk-synthetic_legacy_key_20261025',
        'workspace-dotted': 'sk-ws-synthetic.alpha_20261025-BETA.delta',
        'minimum-length': 's' * 16,
        'maximum-length': 's' * 512,
    }
    rejected = {
        'internal-space': 'sk-synthetic key_for_verification',
        'bearer-prefix': 'Bearer sk-synthetic_key_for_verification',
        'internal-crlf': 'sk-synthetic_key\r\nInjected-header',
        'internal-cr': 'sk-synthetic_key\rInjected-header',
        'internal-lf': 'sk-synthetic_key\nInjected-header',
        'non-ascii': 'sk-synthetic_\u6d4b\u8bd5_key_for_verification',
        'too-short': 's' * 15,
        'too-long': 's' * 513,
        'slash': 'sk-synthetic/key_for_verification',
        'colon': 'sk-synthetic:key_for_verification',
    }
    with tempfile.TemporaryDirectory(prefix='airi-key-format-synthetic-') as temporary:
        fixture = Path(temporary)
        configuration.ROOT = fixture
        engine.config_store.ROOT = fixture

        def forbid_network(*_args, **_kwargs):
            raise AssertionError('NETWORK_FORBIDDEN')

        with mock.patch.object(socket.socket, 'connect', forbid_network), \
                mock.patch('socket.create_connection', forbid_network):
            for label, synthetic in accepted.items():
                target = fixture / label

                def save_and_roundtrip(target=target, synthetic=synthetic):
                    result = configuration.save_settings({'apiKey': synthetic}, root=target)
                    loaded = configuration.load_private_settings(root=target)
                    return result['configured'] is True and loaded['apiKey'] == synthetic

                check(label + ':save-dpapi-load', save_and_roundtrip)

                def protected_only(target=target, synthetic=synthetic):
                    encoded = (target / 'private' / 'settings.json').read_text(encoding='utf-8')
                    stored = json.loads(encoded)
                    return bool(stored.get('protectedKey')) and synthetic not in encoded and 'apiKey' not in stored

                check(label + ':encrypted-storage', protected_only)

                def public_redacted(target=target, synthetic=synthetic):
                    result = configuration.get_public_settings(root=target)
                    return result['keyConfigured'] is True and synthetic not in json.dumps(result) and 'protectedKey' not in result

                check(label + ':public-redacted', public_redacted)

                def construct_request(target=target, synthetic=synthetic):
                    loaded = configuration.load_private_settings(root=target)
                    request, _, model = engine._request_spec('Synthetic speech fixture.', loaded)
                    return (model == 'qwen3-tts-flash'
                            and request.get_header('Authorization') == 'Bearer ' + synthetic
                            and request.get_method() == 'POST')

                check(label + ':request-header', construct_request)

            def expressive_workspace_request():
                synthetic = accepted['workspace-dotted']
                target = fixture / 'expressive-workspace'
                configuration.save_settings({
                    'apiKey': synthetic, 'region': 'beijing', 'mode': 'expressive',
                    'apiHost': 'https://synthetic-fixture.cn-beijing.maas.aliyuncs.com',
                    'voice': 'longanlingxin_v3.1',
                }, root=target)
                request, _, model = engine._request_spec('Synthetic speech fixture.', configuration.load_private_settings(root=target))
                body = json.loads(request.data)
                return (model == 'qwen-audio-3.1-tts-flash'
                        and request.full_url == 'https://synthetic-fixture.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer'
                        and request.get_header('Authorization') == 'Bearer ' + synthetic
                        and body['input']['voice'] == 'longanlingxin_v3.1')

            check('workspace-dotted:expressive-request', expressive_workspace_request)

            for label, malformed in rejected.items():
                target = fixture / ('reject-' + label)

                def invalid_save(target=target, malformed=malformed):
                    try:
                        configuration.save_settings({'apiKey': malformed}, root=target)
                    except configuration.ConfigError as error:
                        return error.code == 'INVALID_API_KEY' and not (target / 'private' / 'settings.json').exists()
                    return False

                check(label + ':save-rejected', invalid_save)

                def invalid_load(target=target, malformed=malformed):
                    target.mkdir(parents=True, exist_ok=True)
                    configuration._atomic_json(target / 'private' / 'settings.json', {
                        **configuration.DEFAULTS, 'protectedKey': configuration._protect_key(malformed),
                    })
                    try:
                        configuration.load_private_settings(root=target)
                    except configuration.ConfigError as error:
                        return error.code == 'CREDENTIAL_UNAVAILABLE'
                    return False

                check(label + ':decrypted-value-rejected', invalid_load)

                def invalid_request(malformed=malformed):
                    try:
                        engine._request_spec('Synthetic speech fixture.', {**configuration.DEFAULTS, 'apiKey': malformed})
                    except engine.EngineError as error:
                        return error.code == 'API_KEY_NOT_CONFIGURED'
                    return False

                check(label + ':request-rejected', invalid_request)

    total = passed + len(failed)
    print(json.dumps({
        'test': 'synthetic-key-formats-dpapi-and-request-construction',
        'passed': passed, 'total': total, 'success': not failed,
        'failedChecks': failed, 'realCredentialsRead': False,
        'realCloudRequests': 0, 'realSettingsChanged': False,
        'temporaryDirectoryRemoved': not fixture.exists(),
        'scope': 'Synthetic key validation and current-user DPAPI only; no cloud authentication or AIRI playback.',
    }, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == '__main__':
    raise SystemExit(run())
