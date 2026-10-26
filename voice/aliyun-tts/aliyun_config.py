# SPDX-License-Identifier: MIT
"""Private current-user settings for the optional Aliyun speech adapter.

Cloud credentials are protected by Windows DPAPI. Only explicit configuration
operations decrypt them; public settings never include a key or key prefix.
"""
from __future__ import annotations

import base64
import contextlib
import ctypes
from ctypes import wintypes
import datetime
import json
import os
from pathlib import Path
import re
import secrets
import threading
import urllib.parse

ROOT = Path(__file__).resolve().parent
MODEL_ALIAS = 'aliyun-qwen-tts'
DEFAULTS = {'region': 'beijing', 'mode': 'simple', 'apiHost': '', 'voice': 'Serena',
            'style': 'gentle', 'instruction': ''}
SIMPLE_VOICES = [('Serena', 'Serena · 温柔女声'), ('Maia', 'Maia · 知性温柔'), ('Seren', 'Seren · 舒缓女声')]
EXPRESSIVE_VOICES = [('longanlingxin_v3.1', '龙安灵心 · 女声'),
                    ('longanhuan_v3.1', '龙安欢 · 女声'), ('longanfengyue_v3.1', '龙安风悦 · 女声'),
                    ('xunanchuan_v3.1', '许南川 · 男声')]
BEIJING_VOICES = [('anruorou_v3.1', '安若柔 · 气声知性'), ('xieshurou_v3.1', '谢舒柔 · 柔和知性'),
                  ('longwan_v3.1', '龙婉 · 细腻柔声')]
STYLES = ('gentle', 'drowsy', 'focused', 'neutral')
_LOCK = threading.RLock()


class ConfigError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _root(root=None):
    return Path(root) if root is not None else ROOT


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
    try:
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def _transaction(root):
    with _LOCK:
        directory = _root(root) / 'private'
        directory.mkdir(parents=True, exist_ok=True)
        if os.name != 'nt':
            yield
            return
        import msvcrt
        with (directory / 'settings.lock').open('a+b') as stream:
            if stream.tell() == 0:
                stream.write(b'0'); stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def _read(root=None):
    path = _root(root) / 'private' / 'settings.json'
    try:
        if path.stat().st_size > 65536:
            raise ConfigError('INVALID_SETTINGS', '阿里语音设置文件无效，请重新保存。')
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except FileNotFoundError:
        return {}
    except (ValueError, UnicodeError, OSError):
        raise ConfigError('INVALID_SETTINGS', '阿里语音设置文件无效，请重新保存。') from None


class _Blob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data, decrypt=False):
    if os.name != 'nt':
        raise ConfigError('DPAPI_UNAVAILABLE', '密钥保存需要 Windows 当前用户保护；此平台未启用凭证存储。')
    if not isinstance(data, bytes) or not data or len(data) > 32768:
        raise ConfigError('INVALID_CREDENTIAL', '本机密钥数据无效，请重新填写。')
    buffer = ctypes.create_string_buffer(data, len(data))
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = _Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    crypt.CryptProtectData.argtypes = [ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    crypt.CryptProtectData.restype = wintypes.BOOL
    crypt.CryptUnprotectData.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    crypt.CryptUnprotectData.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    # CRYPTPROTECT_UI_FORBIDDEN; scope remains current Windows user, never LOCAL_MACHINE.
    ok = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)) if decrypt else \
        crypt.CryptProtectData(ctypes.byref(source), 'AIRI Aliyun TTS credential', None, None, None, 1, ctypes.byref(target))
    if not ok:
        raise ConfigError('CREDENTIAL_UNAVAILABLE', '无法使用当前 Windows 用户的阿里密钥，请在本机重新保存。')
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        if target.pbData:
            ctypes.memset(target.pbData, 0, target.cbData)
            kernel.LocalFree(target.pbData)
        ctypes.memset(buffer, 0, len(data))


def _protect_key(key):
    return base64.b64encode(_dpapi(key.encode('utf-8'))).decode('ascii')


def _unprotect_key(value):
    try:
        return _dpapi(base64.b64decode(value, validate=True), decrypt=True).decode('utf-8')
    except (ValueError, UnicodeError, TypeError):
        raise ConfigError('CREDENTIAL_UNAVAILABLE', '本机密钥数据无效，请重新保存。') from None


def voices_for(mode, region):
    values = SIMPLE_VOICES if mode == 'simple' else EXPRESSIVE_VOICES + (BEIJING_VOICES if region == 'beijing' else [])
    return [{'id': identifier, 'name': name} for identifier, name in values]


def _host(value, region):
    if not isinstance(value, str) or len(value) > 200:
        raise ConfigError('INVALID_API_HOST', '请填写百炼控制台复制的 API Host。')
    value = value.strip()
    if not value:
        return ''
    if '://' not in value:
        value = 'https://' + value
    try:
        url = urllib.parse.urlsplit(value)
        suffix = 'cn-beijing' if region == 'beijing' else 'ap-southeast-1'
        if (url.scheme != 'https' or url.username or url.password or url.query or url.fragment
                or url.port not in (None, 443) or url.path not in ('', '/')
                or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,99}\.' + re.escape(suffix) + r'\.maas\.aliyuncs\.com', url.hostname or '')):
            raise ValueError()
        return 'https://' + url.hostname
    except ValueError:
        raise ConfigError('INVALID_API_HOST', 'API Host 必须是所选地域的百炼业务空间 HTTPS 域名，不含路径或查询参数。') from None


def _validated(value):
    if not isinstance(value, dict):
        raise ConfigError('INVALID_SETTINGS', '阿里语音设置无效。')
    result = {key: value.get(key, default) for key, default in DEFAULTS.items()}
    if result['region'] not in ('beijing', 'singapore') or result['mode'] not in ('simple', 'expressive'):
        raise ConfigError('INVALID_SETTINGS', '请选择支持的地域和语音模式。')
    if result['style'] not in STYLES:
        raise ConfigError('INVALID_STYLE', '请选择有效的语气。')
    result['apiHost'] = _host(result['apiHost'], result['region'])
    if result['voice'] not in {item['id'] for item in voices_for(result['mode'], result['region'])}:
        raise ConfigError('INVALID_VOICE', '该音色不适用于所选模式或地域，请重新选择。')
    if (not isinstance(result['instruction'], str) or len(result['instruction']) > 300
            or any(ord(char) < 32 and char not in '\n\t' for char in result['instruction'])):
        raise ConfigError('INVALID_INSTRUCTION', '语气说明最多 300 个字符。')
    result['instruction'] = result['instruction'].strip()
    return result


def get_public_settings(root=None):
    stored = _read(root)
    fields = _validated(stored)
    key_configured = bool(stored.get('protectedKey'))
    last_test = None
    raw_test = stored.get('lastTest')
    if isinstance(raw_test, dict) and raw_test.get('status') in ('success', 'failed'):
        try:
            stamp = raw_test.get('checkedAt', '')
            if not isinstance(stamp, str) or len(stamp) > 50:
                raise ValueError()
            datetime.datetime.fromisoformat(stamp)
            last_test = {'status': raw_test['status'], 'checkedAt': stamp}
            if raw_test['status'] == 'success':
                timings = raw_test.get('timings', {})
                selected = {key: timings[key] for key in ('firstAudioMs', 'completeWavMs', 'audioDurationSeconds')}
                if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 600000 for value in selected.values()):
                    raise ValueError()
                last_test['timings'] = selected
            else:
                code = raw_test.get('code', 'TEST_FAILED')
                last_test['code'] = code if isinstance(code, str) and re.fullmatch('[A-Z_0-9]{1,80}', code) else 'TEST_FAILED'
        except (ValueError, TypeError, KeyError):
            last_test = None
    revision = stored.get('revision')
    if not isinstance(revision, str) or not re.fullmatch('[a-f0-9]{24}', revision):
        revision = None
    return {**fields, 'model': 'qwen3-tts-flash' if fields['mode'] == 'simple' else 'qwen-audio-3.1-tts-flash',
            'modelAlias': MODEL_ALIAS, 'keyConfigured': key_configured,
            'configured': key_configured and (fields['mode'] == 'simple' or bool(fields['apiHost'])),
            'styleSupported': fields['mode'] == 'expressive', 'voices': voices_for(fields['mode'], fields['region']),
            'revision': revision, 'lastTest': last_test,
            'cloudTested': bool(last_test and last_test['status'] == 'success'),
            'streamingPlayback': False}


def save_settings(payload, root=None):
    allowed = set(DEFAULTS) | {'apiKey', 'clearKey'}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise ConfigError('INVALID_SETTINGS', '阿里语音配置字段无效。')
    if 'clearKey' in payload and not isinstance(payload['clearKey'], bool):
        raise ConfigError('INVALID_SETTINGS', '清除密钥选项无效。')
    with _transaction(root):
        stored = _read(root)
        combined = {**DEFAULTS, **{key: stored[key] for key in DEFAULTS if key in stored}, **{key: payload[key] for key in DEFAULTS if key in payload}}
        # Switching modes chooses the corresponding default when a caller did not choose a voice.
        if 'mode' in payload and payload['mode'] != stored.get('mode', 'simple') and 'voice' not in payload:
            combined['voice'] = 'Serena' if payload['mode'] == 'simple' else 'longanlingxin_v3.1'
        fields = _validated(combined)
        key = payload.get('apiKey', '')
        if not isinstance(key, str) or (key and not re.fullmatch(r'[A-Za-z0-9_.-]{16,512}', key.strip())):
            raise ConfigError('INVALID_API_KEY', 'API Key 格式无效，请直接粘贴百炼密钥，不加 Bearer 前缀。')
        if payload.get('clearKey') and key.strip():
            raise ConfigError('INVALID_API_KEY', '不能同时填写和清除密钥。')
        protected = stored.get('protectedKey', '')
        if payload.get('clearKey'):
            protected = ''
        elif key.strip():
            protected = _protect_key(key.strip())
        updated = {**fields, 'schemaVersion': 1, 'revision': secrets.token_hex(12), 'protectedKey': protected}
        _atomic_json(_root(root) / 'private' / 'settings.json', updated)
    return get_public_settings(root)


def load_private_settings(root=None):
    stored = _read(root)
    fields = _validated(stored)
    if not stored.get('protectedKey'):
        raise ConfigError('API_KEY_NOT_CONFIGURED', '请先在控制台保存阿里云 API Key。')
    if fields['mode'] == 'expressive' and not fields['apiHost']:
        raise ConfigError('API_HOST_NOT_CONFIGURED', '情绪语音需要填写百炼控制台的 API Host。')
    key = _unprotect_key(stored['protectedKey'])
    if not re.fullmatch(r'[A-Za-z0-9_.-]{16,512}', key):
        raise ConfigError('CREDENTIAL_UNAVAILABLE', '本机密钥数据无效，请重新保存。')
    return {**fields, 'apiKey': key, 'revision': stored.get('revision')}


def record_test(result, root=None, expectedRevision=None, expected_revision=None):
    if not isinstance(result, dict):
        raise ConfigError('INVALID_TEST_RESULT', '试听结果无效。')
    if expected_revision is not None:
        expectedRevision = expected_revision
    status = 'success' if result.get('status') in ('success', 'passed') else 'failed'
    record = {'status': status, 'checkedAt': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    if status == 'success':
        timings = result.get('timings', {})
        selected = {}
        for key in ('firstAudioMs', 'completeWavMs', 'audioDurationSeconds'):
            value = timings.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 600000:
                raise ConfigError('INVALID_TEST_RESULT', '试听测速数据无效。')
            selected[key] = round(value, 3)
        record['timings'] = selected
    else:
        code = result.get('code', result.get('errorCode', 'TEST_FAILED'))
        record['code'] = code if isinstance(code, str) and re.fullmatch('[A-Z_0-9]{1,80}', code) else 'TEST_FAILED'
    with _transaction(root):
        stored = _read(root)
        if expectedRevision is not None and stored.get('revision') != expectedRevision:
            return False
        stored['lastTest'] = record
        _atomic_json(_root(root) / 'private' / 'settings.json', stored)
    return True


def ensure_token(path=None):
    target = Path(path) if path is not None else ROOT / 'api-token.txt'
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.with_name(target.name + '.' + secrets.token_hex(8) + '.tmp')
        try:
            with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='ascii') as stream:
                stream.write(secrets.token_urlsafe(32)); stream.flush(); os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                pass
        finally:
            temporary.unlink(missing_ok=True)
    token = target.read_text(encoding='ascii').strip()
    if not re.fullmatch('[A-Za-z0-9_-]{43}', token):
        raise ConfigError('INVALID_LOCAL_TOKEN', '本机语音连接密钥文件无效。')
    return token
