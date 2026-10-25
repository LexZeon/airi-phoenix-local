"""Validated local AIRI module selection. No downloads, arbitrary execution or card replacement."""
from __future__ import annotations
import argparse
import copy
import datetime
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import threading
from contextlib import contextmanager
import msvcrt
import urllib.parse

ROOT = Path(__file__).resolve().parent
BASE = Path(os.environ.get('AIRI_COMPANIONS_ROOT', str(ROOT.parent))).expanduser().resolve()
DATA_ROOT = Path(os.environ.get('AIRI_CONTROL_DATA_DIR', str(ROOT / 'state'))).expanduser().resolve()
CONTROL_PORT = int(os.environ.get('AIRI_CONTROL_PORT', '9944'))
SETTINGS = Path(os.environ.get('AIRI_OFFLINE_SETTINGS', str(BASE / 'runtime/airi-offline/offline-settings.json'))).expanduser().resolve()
PREFERENCES = DATA_ROOT / 'preferences.json'
REQUESTS = DATA_ROOT / 'requests'
LOCK = threading.RLock()
MODULES = ('chat', 'vision', 'asr', 'tts')
DEFAULT = {'chat': 'qwen9', 'vision': 'vision9', 'asr': 'sensevoice', 'tts': 'qwen-soft'}
CHOICES = {
 'qwen9': ('chat', 'http://127.0.0.1:9941/v1/', 'airi-qwen3.5-9b', None),
 'qwen27': ('chat', 'http://127.0.0.1:9931/v1/', 'spark-primary', None),
 'vision9': ('vision', 'http://127.0.0.1:9941/v1/', 'airi-qwen3.5-9b', None),
 'sensevoice': ('asr', 'http://127.0.0.1:9942/v1/', 'sensevoice-local', None),
 'melo': ('tts', 'http://127.0.0.1:9942/v1/', 'melo-tts-zh-en', 'zh_default'),
 'qwen-soft': ('tts', 'http://127.0.0.1:9945/v1/', 'phoenix-qwen3-tts-local', 'phoenix-soft'),
 'qwen-drowsy': ('tts', 'http://127.0.0.1:9945/v1/', 'phoenix-qwen3-tts-local', 'phoenix-drowsy'),
 'qwen-focused': ('tts', 'http://127.0.0.1:9945/v1/', 'phoenix-qwen3-tts-local', 'phoenix-focused'),
}

def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def read_json(path, fallback=None):
    try: return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError): return fallback

def atomic_json(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + secrets.token_hex(6) + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists(): temporary.unlink()

@contextmanager
def settings_transaction():
    # Serialize the HTTP server and manual PowerShell helper across processes.
    with LOCK:
        path = DATA_ROOT / 'profile-apply.lock'
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a+b') as stream:
            if stream.tell() == 0: stream.write(b'0'); stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            try: yield
            finally:
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)

def local_url(value):
    if not isinstance(value, str) or len(value) > 512: raise ValueError('请输入有效的本机服务地址。')
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.scheme != 'http' or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('仅接受 http 本机地址，不接受密钥、查询或跳转参数。')
    host = parsed.hostname
    if host == 'localhost': host = '127.0.0.1'
    try:
        if not ipaddress.ip_address(host).is_loopback: raise ValueError()
        port = parsed.port or 80
    except (ValueError, TypeError): raise ValueError('仅接受 127.0.0.1、localhost 或 ::1 本机地址。') from None
    if host not in ('127.0.0.1', '::1') or port == CONTROL_PORT: raise ValueError('地址必须指向本机模型服务，不能指向控制台。')
    path = parsed.path or '/v1/'
    if not re.fullmatch(r'/[A-Za-z0-9_./-]*', path) or '..' in path or '//' in path:
        raise ValueError('服务路径无效。')
    return f'http://{"[::1]" if host == "::1" else host}:{port}' + path.rstrip('/') + '/'

def text(value, label, limit=160, optional=False):
    if not isinstance(value, str) or len(value) > limit or any(ord(c)<32 for c in value): raise ValueError(label + '无效。')
    value = value.strip()
    if not value and not optional: raise ValueError('请填写' + label + '。')
    return value

def normalize(data):
    if not isinstance(data, dict) or set(data) - {'selections','custom'}: raise ValueError('配置字段无效。')
    selections = data.get('selections')
    if not isinstance(selections, dict) or set(selections) != set(MODULES): raise ValueError('需要选择聊天、看屏幕、听你说话和角色声音四项。')
    custom = data.get('custom', {})
    if not isinstance(custom, dict) or set(custom)-set(MODULES): raise ValueError('兼容服务字段无效。')
    result = {'selections': {}, 'custom': {}}
    for module in MODULES:
        choice = selections[module]
        if not isinstance(choice, str): raise ValueError('方案无效。')
        if choice in ('custom', 'ollama'):
            if choice == 'ollama' and module not in ('chat','vision'): raise ValueError('Ollama仅用于聊天或看屏幕。')
            item = custom.get(module, {})
            if not isinstance(item, dict) or set(item)-{'baseUrl','model','voice','apiKey'}: raise ValueError('兼容服务字段无效。')
            endpoint = 'http://127.0.0.1:11434/v1/' if choice == 'ollama' else local_url(item.get('baseUrl'))
            result['custom'][module] = {'baseUrl': endpoint, 'model': text(item.get('model'), '模型名称'),
                'apiKey': text(item.get('apiKey','local'), '本机服务密钥', 512, True) or 'local'}
            if module == 'tts': result['custom'][module]['voice'] = text(item.get('voice',''), '音色', 160, True)
        elif choice not in CHOICES or CHOICES[choice][0] != module: raise ValueError('这个方案不能用于当前模块。')
        result['selections'][module] = choice
    return result

def endpoint(profile, module):
    choice = profile['selections'][module]
    if choice in ('custom','ollama'): return dict(profile['custom'][module])
    _, base, model, voice = CHOICES[choice]
    return {'baseUrl': base, 'model': model, 'apiKey': 'local-offline' if module in ('asr','tts') else 'local', 'voice': voice}

def current_profile():
    config = read_json(SETTINGS, {})
    remembered = config.get('controlCenterSelection')
    if remembered:
        try: return normalize(remembered)
        except ValueError: pass
    result = {'selections': dict(DEFAULT), 'custom': {}}
    providers = config.get('providers', {})
    for module, key in [('chat','consciousness'),('vision','vision'),('asr','hearing'),('tts','speech')]:
        selected = config.get('modules', {}).get(key, {})
        provider = providers.get(selected.get('provider'),{}).get('config',{})
        model = selected.get('model') or config.get('storage',{}).get(f'settings/{key}/active-model') or provider.get('model')
        base = provider.get('baseUrl','')
        voice = selected.get('voice_id') or provider.get('voice') or config.get('storage',{}).get('settings/speech/voice')
        match = next((id_ for id_, values in CHOICES.items() if values[0] == module and values[1] == base and values[2] == model and (module!='tts' or values[3] == voice)), None)
        if match: result['selections'][module] = match
        elif base and model:
            try:
                result['custom'][module] = {'baseUrl':local_url(base),'model':model,'apiKey':provider.get('apiKey','local')}
                if module=='tts': result['custom'][module]['voice']=voice or ''
                result['selections'][module]='custom'
            except ValueError: pass
    return result

def public_profile(profile):
    value = copy.deepcopy(profile)
    for item in value.get('custom',{}).values():
        item['hasApiKey'] = bool(item.pop('apiKey',None))
    return value

def merge_input(data):
    # Empty password fields preserve the locally stored key for the same service/model.
    if not isinstance(data, dict): raise ValueError('需要有效的四项设置。')
    if not isinstance(data.get('custom', {}), dict): raise ValueError('兼容服务字段无效。')
    data = copy.deepcopy(data)
    stored = read_json(PREFERENCES, {}).get('profile', current_profile())
    for module, item in data.get('custom',{}).items():
        if isinstance(item, dict):
            item.pop('hasApiKey',None)
            previous = stored.get('custom',{}).get(module,{})
            if not item.get('apiKey') and item.get('baseUrl') == previous.get('baseUrl') and item.get('model') == previous.get('model'):
                item['apiKey'] = previous.get('apiKey','local')
    return normalize(data)

def apply_profile(profile, settings_path=SETTINGS):
    profile = normalize(profile)
    with settings_transaction():
        settings_path = Path(settings_path)
        raw = settings_path.read_bytes()
        config = json.loads(raw.decode('utf-8-sig'))
        revision = 'airi-selection-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + secrets.token_hex(4)
        overrides = {}
        for module, key in [('chat','consciousness'),('vision','vision'),('asr','hearing'),('tts','speech')]:
            chosen = endpoint(profile,module)
            provider_id = 'control-center-' + key
            definition = 'openai-compatible-audio-transcription' if module=='asr' else 'openai-compatible-audio-speech' if module=='tts' else 'openai-compatible'
            provider_config = {'baseUrl': chosen['baseUrl'], 'apiKey': chosen['apiKey']}
            if module in ('chat','vision'): provider_config['api']='chat-completions'
            else: provider_config['model']=chosen['model']
            if module=='asr': provider_config['language']='zh'
            if module=='tts': provider_config.update(voice=chosen.get('voice') or '', speed=1)
            config.setdefault('providers',{})[provider_id] = {'id':provider_id,'definitionId':definition,'config':provider_config,'status':'configured','configuredBy':'user'}
            values = {'provider':provider_id,'model':chosen['model']}
            if module=='tts': values['voice_id']=chosen.get('voice') or ''
            config.setdefault('modules',{}).setdefault(key,{}).update(values)
            overrides[key] = values
            storage = config.setdefault('storage',{})
            for suffix,value in [('active-provider',provider_id),('active-model',chosen['model']),('active-custom-model',chosen['model'])]: storage[f'settings/{key}/{suffix}']=value
            if module=='tts': storage['settings/speech/voice']=chosen.get('voice') or ''
            if module=='vision': config.setdefault('screen',{}).update(baseUrl=chosen['baseUrl'],model=chosen['model'])
        config.setdefault('character',{})['modulesOverride']=overrides
        config['character']['selectionRevision']=revision
        config['controlCenterSelection']=profile
        config['revision']=revision
        backup = settings_path.with_name(settings_path.name + '.' + revision + '.bak')
        with backup.open('xb') as stream: stream.write(raw)
        atomic_json(settings_path,config)
        return {'ok':True,'revision':revision,'backup':str(backup),'settings':str(settings_path),'profile':public_profile(profile),'restartRequired':True,
                'message':'已更新 AIRI 的实际四模块配置，并保留备份。重启 AIRI 后生效。'}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply-file',type=Path,required=True);args=parser.parse_args()
    request=args.apply_file.resolve();request.relative_to(REQUESTS.resolve())
    if not re.fullmatch(r'selection-[a-f0-9]{32}\.json', request.name) or request.parent != REQUESTS.resolve(): raise SystemExit('Invalid managed request path')
    print(json.dumps(apply_profile(read_json(request)),ensure_ascii=False))
