# SPDX-License-Identifier: MIT
"""Synthetic completed-SSE streaming WAV regression checks; no private state.

Imports source only, never loads settings, and supplies an in-memory fake
opener. Every network connection is blocked while checks run.
"""
from __future__ import annotations

import base64
import importlib.util
import io
import json
from pathlib import Path
import socket
import struct
from unittest import mock
import wave

SOURCE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('isolated_stream_wav_engine', SOURCE / 'engine.py')
engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(engine)
PCM = b'\x00\x00\x10\x00' * 39360  # 157440 bytes, no user-derived audio.
CFG = {**engine.config_store.DEFAULTS, 'mode': 'expressive',
       'voice': 'longanlingxin_v3.1', 'apiKey': 'synthetic.workspace.key_for_fixture',
       'apiHost': 'https://synthetic-fixture.cn-beijing.maas.aliyuncs.com'}


def header(pcm=PCM, riff=0x7FFFFFBF, size=0x7FFFFF9B):
    regular, _ = engine._pcm_wav(pcm)
    result = bytearray(regular)
    struct.pack_into('<I', result, 4, riff)
    struct.pack_into('<I', result, 40, size)
    return bytes(result)


class FakeResponse(io.BytesIO):
    headers = {'Content-Type': 'text/event-stream'}


class FakeOpener:
    def __init__(self, data, finish=True, done=False, cancel=None):
        events = [{'output': {'audio': {'data': base64.b64encode(part).decode('ascii')}}}
                  for part in (data[:31], data[31:100], data[100:]) if part]
        if finish:
            events.append({'output': {'finish_reason': 'stop', 'audio': {'data': ''}}})
        self.body = b''.join(('data: ' + json.dumps(event) + '\n\n').encode() for event in events)
        if done:
            self.body += b'data: [DONE]\n\n'
        self.calls = 0

    def open(self, request, timeout):
        self.calls += 1
        return FakeResponse(self.body)


def frames(audio):
    with wave.open(io.BytesIO(audio), 'rb') as result:
        return result.readframes(result.getnframes())


def rejected(action, expected=None):
    try:
        action()
    except engine.EngineError as error:
        return expected is None or error.code == expected
    return False


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
            failed.append(name)

    def forbid(*_args, **_kwargs):
        raise AssertionError('NETWORK_FORBIDDEN')

    normal, _ = engine._pcm_wav(PCM)
    observed = header()
    with mock.patch.object(socket.socket, 'connect', forbid), \
            mock.patch('socket.create_connection', forbid), \
            mock.patch.object(engine.config_store, 'load_private_settings', side_effect=AssertionError('PRIVATE_CONFIG_FORBIDDEN')):
        check('metadata-exact-observed-shape', lambda: len(observed) == 157484)
        check('placeholder-disabled-by-default', lambda: rejected(lambda: engine._validated_wav(observed), 'INCOMPLETE_WAV_AUDIO'))
        check('placeholder-normalized-after-stop', lambda: engine._validated_wav(observed, allow_streaming_placeholder=True) == (normal, 3.28))
        check('standard-wav-unchanged', lambda: engine._validated_wav(normal)[0] == normal)
        check('standard-wav-with-stream-flag-unchanged', lambda: engine._validated_wav(normal, allow_streaming_placeholder=True)[0] == normal)
        check('standard-concatenation-preserved', lambda: frames(engine._validated_wav(normal + normal)[0]) == PCM + PCM)
        check('standard-concatenation-with-stream-flag', lambda: frames(engine._validated_wav(normal + normal, allow_streaming_placeholder=True)[0]) == PCM + PCM)

        def synthetic_completed_sse():
            result = engine.synthesize('Synthetic test sentence.', CFG, opener=FakeOpener(observed))
            return result['wav'] == normal and result['timings']['audioDurationSeconds'] == 3.28

        check('completed-sse-accepts-exact-placeholder', synthetic_completed_sse)
        check('missing-stop-rejected-before-normalization', lambda: rejected(lambda: engine.synthesize('Synthetic.', CFG, opener=FakeOpener(observed, finish=False)), 'INCOMPLETE_UPSTREAM_AUDIO'))
        check('done-marker-alone-not-a-success-stop', lambda: rejected(lambda: engine.synthesize('Synthetic.', CFG, opener=FakeOpener(observed, finish=False, done=True)), 'INCOMPLETE_UPSTREAM_AUDIO'))
        check('completed-sse-normal-concatenation', lambda: frames(engine.synthesize('Synthetic.', CFG, opener=FakeOpener(normal + normal))['wav']) == PCM + PCM)

        malformed = {
            'finite-truncation': normal[:-2],
            'finite-truncation-odd': normal[:-1],
            'finite-trailing-bytes': normal + b'extra!',
            'placeholder-odd-frame': observed[:-1],
            'placeholder-empty-payload': observed[:44],
            'unknown-riff-placeholder': header(riff=0xFFFFFFFF),
            'unknown-data-placeholder': header(size=0xFFFFFFFF),
            'arbitrary-large-size-pair': header(riff=0x70000024, size=0x70000000),
            'placeholder-plus-normal-container': observed + normal,
            'two-placeholder-containers': observed + observed,
            'truncated-header': observed[:40],
            'non-wave-tag': observed[:8] + b'NOPE' + observed[12:],
        }
        for name, value in malformed.items():
            check(name + ':validator-rejected', lambda value=value: rejected(lambda: engine._validated_wav(value, allow_streaming_placeholder=True)))
            check(name + ':completed-sse-rejected', lambda value=value: rejected(lambda: engine.synthesize('Synthetic.', CFG, opener=FakeOpener(value))))

        field_changes = {
            'compressed-format': (20, '<H', 3),
            'stereo-placeholder': (22, '<H', 2),
            'wrong-sample-rate': (24, '<I', 16000),
            'wrong-byte-rate': (28, '<I', 47000),
            'wrong-block-align': (32, '<H', 4),
            'wrong-bits': (34, '<H', 24),
            'extra-fmt-data': (16, '<I', 18),
        }
        for name, (offset, fmt, value) in field_changes.items():
            malformed_value = bytearray(observed)
            struct.pack_into(fmt, malformed_value, offset, value)
            check(name + ':placeholder-rejected', lambda malformed_value=bytes(malformed_value): rejected(lambda: engine._validated_wav(malformed_value, allow_streaming_placeholder=True)))
        second, _ = engine._pcm_wav(PCM, rate=16000)
        check('inconsistent-standard-fragments-rejected', lambda: rejected(lambda: engine._validated_wav(normal + second, allow_streaming_placeholder=True)))
    print(json.dumps({
        'test': 'completed-sse-known-streaming-wav-placeholder',
        'passed': passed, 'total': passed + len(failed), 'success': not failed,
        'failedChecks': failed, 'realCredentialsRead': False, 'realCloudRequests': 0,
        'realSettingsChanged': False,
        'scope': 'Synthetic WAV containers and completed SSE only; not cloud latency, voice quality or actual AIRI playback.',
    }))
    return 0 if not failed else 1


if __name__ == '__main__':
    raise SystemExit(run())
