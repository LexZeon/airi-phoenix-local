"""Private Aliyun TTS configuration and user-triggered synthetic previews for the console."""
from __future__ import annotations

import copy
import datetime
import importlib.util
import io
import math
import os
from pathlib import Path
import sys
import threading
import wave


PUBLIC_FIELDS = ('region', 'mode', 'apiHost', 'voice', 'style', 'instruction', 'keyConfigured',
                 'configured', 'revision', 'model', 'modelAlias', 'styleSupported', 'voices', 'cloudTested', 'streamingPlayback')


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def safe_timings(value):
    if not isinstance(value, dict):
        raise ValueError('试听未返回有效的测速结果。')
    result = {}
    for name in ('firstAudioMs', 'completeWavMs', 'audioDurationSeconds'):
        number = value.get(name)
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number < 0:
            raise ValueError('试听未返回有效的测速结果。')
        result[name] = round(float(number), 3)
    if result['completeWavMs'] < result['firstAudioMs'] or not 0 < result['audioDurationSeconds'] <= 300:
        raise ValueError('试听未返回有效的测速结果。')
    return result


def public_test(value):
    if not isinstance(value, dict):
        return None
    result = {key: copy.deepcopy(value[key]) for key in ('status', 'testedAt', 'checkedAt', 'model', 'voice', 'code', 'errorCode') if key in value}
    if isinstance(value.get('timings'), dict):
        try:
            result['timings'] = safe_timings(value['timings'])
        except ValueError:
            pass
    return result


class AliyunTtsBridge:
    def __init__(self, root, config_module=None, engine_module=None):
        self.root = Path(root).resolve()
        self.runtime = Path(os.environ.get('AIRI_ALIYUN_TTS_ROOT', str(self.root.parent / 'runtime' / 'airi-aliyun-tts'))).expanduser().resolve()
        self.config_module = config_module
        self.engine_module = engine_module
        self.module_lock = threading.RLock()
        self.test_lock = threading.Lock()
        self.sample = None
        self.last_test = None
        self.last_test_revision = None

    def _module(self, name):
        field = 'config_module' if name == 'aliyun_config' else 'engine_module'
        with self.module_lock:
            existing = getattr(self, field)
            if existing is not None:
                return existing
            source = self.runtime / (name + '.py')
            if not source.is_file():
                raise ValueError('阿里云语音连接程序尚未安装。')
            alias = 'airi_console_aliyun_' + name
            spec = importlib.util.spec_from_file_location(alias, source)
            if not spec or not spec.loader:
                raise ValueError('阿里云语音连接程序无法加载。')
            module = importlib.util.module_from_spec(spec)
            sys.modules[alias] = module
            spec.loader.exec_module(module)
            setattr(self, field, module)
            return module

    def status(self):
        try:
            data = self._module('aliyun_config').get_public_settings(root=self.runtime)
            result = {key: copy.deepcopy(data[key]) for key in PUBLIC_FIELDS if key in data}
            result['available'] = True
            result['keyConfigured'] = data.get('keyConfigured') is True
            result['configured'] = data.get('configured') is True
            measured = self.last_test if self.last_test_revision == data.get('revision') else None
            measured = measured or public_test(data.get('lastTest'))
            if measured:
                result['lastTest'] = measured
            result['sampleAvailable'] = self.sample is not None
            return result
        except (OSError, ValueError, ImportError):
            return {'available': False, 'configured': False, 'keyConfigured': False,
                    'region': 'beijing', 'mode': 'simple', 'voice': 'Serena', 'style': 'gentle',
                    'styleSupported': False, 'model': 'qwen3-tts-flash', 'sampleAvailable': False}

    def save(self, payload):
        if not isinstance(payload, dict):
            raise ValueError('需要有效的阿里云语音设置。')
        # The runtime module owns the whitelist and DPAPI encryption. Never echo its raw return value.
        self._module('aliyun_config').save_settings(payload, root=self.runtime)
        self.sample = None
        self.last_test = None
        self.last_test_revision = None
        return self.status()

    def test(self):
        self.sample = None
        config = self.status()
        if not config.get('configured'):
            raise ValueError('请先保存阿里云 API Key；情绪语音还需要对应地域的 API Host。')
        if not self.test_lock.acquire(blocking=False):
            raise ValueError('正在试听测速，请等本次完成。')
        try:
            result = self._module('engine').test_synthesis()
            if not isinstance(result, dict) or not isinstance(result.get('wav'), bytes) or len(result['wav']) > 16 * 1024 * 1024:
                raise ValueError('试听未返回有效的声音文件。')
            audio = result['wav']
            try:
                with wave.open(io.BytesIO(audio), 'rb') as wav:
                    if wav.getnchannels() < 1 or wav.getnframes() < 1 or wav.getframerate() < 8000:
                        raise ValueError('试听未返回有效的声音文件。')
            except (wave.Error, EOFError):
                raise ValueError('试听未返回有效的声音文件。') from None
            timings = safe_timings(result.get('timings'))
            measured = {'status': 'success', 'testedAt': utcnow(), 'timings': timings,
                        'model': str(result.get('model', config.get('model', '')))[:100],
                        'voice': str(result.get('voice', config.get('voice', '')))[:100]}
            revision = result.get('configRevision', config.get('revision'))
            recorded = self._module('aliyun_config').record_test(measured, root=self.runtime, expectedRevision=revision)
            if recorded is False:
                raise ValueError('试听期间设置已变化，请重新测试。')
            self.sample = audio
            self.last_test = measured
            self.last_test_revision = revision
            return {'ok': True, 'test': measured, 'sampleUrl': '/api/aliyun/sample.wav',
                    'message': '固定短句已生成。首段音频是云端首包；当前 AIRI 按完整小句播放。'}
        except Exception as error:
            # Vendor payloads can contain request details. Only the runtime's bounded error category escapes.
            code = str(getattr(error, 'code', 'SYNTHESIS_FAILED'))
            if not code or len(code) > 80 or not all(c.isupper() or c.isdigit() or c == '_' for c in code):
                code = 'SYNTHESIS_FAILED'
            self.last_test = {'status': 'failed', 'testedAt': utcnow(), 'code': code}
            self.last_test_revision = config.get('revision')
            try:
                self._module('aliyun_config').record_test(self.last_test, root=self.runtime,
                                                        expectedRevision=config.get('revision'))
            except Exception:
                pass
            friendly = {'AUTHENTICATION_FAILED': 'API Key 未通过验证，请检查地域和密钥。',
                        'RATE_LIMITED': '语音接口暂时限流，请稍后再试。',
                        'NETWORK_ERROR': '暂时无法连接阿里云，请检查网络后重试。',
                        'KEY_NOT_CONFIGURED': '请先保存阿里云 API Key。'}
            raise ValueError(friendly.get(code, '试听未完成（' + code + '）。请检查密钥、地域、模型权限和网络。')) from None
        finally:
            self.test_lock.release()

    def sample_audio(self):
        if self.sample is None:
            raise ValueError('尚无试听音频。请先点“试听测速”。')
        return self.sample
