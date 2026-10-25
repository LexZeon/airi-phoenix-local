"""User-clicked Codex CLI tasks. No AIRI conversation/screen forwarding or auth-file access."""
from __future__ import annotations

import copy
import datetime
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import threading
import time

UUID = re.compile(r'^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$')
TERMINAL = {'success', 'failed', 'stopped'}
MAX_OUTPUT = 64000
MAX_TASK_SECONDS = 1800


def clean_codex_environment():
    """Keep OS/login/proxy discovery, but never inherit an enclosing desktop task's tool pipe or identity."""
    allowed = {'PATH', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'USERPROFILE', 'HOME',
               'APPDATA', 'LOCALAPPDATA', 'HOMEDRIVE', 'HOMEPATH', 'PROGRAMFILES', 'PROGRAMFILES(X86)',
               'PROGRAMW6432', 'PROCESSOR_ARCHITECTURE', 'NUMBER_OF_PROCESSORS', 'HTTP_PROXY', 'HTTPS_PROXY',
               'ALL_PROXY', 'NO_PROXY', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'NODE_EXTRA_CA_CERTS', 'CODEX_HOME'}
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def local_directory(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 1024 or any(ord(c) < 32 for c in value):
        raise ValueError('请选择一个已存在的本地工作文件夹。')
    value = value.strip()
    if value.startswith(('\\\\', '//')):
        raise ValueError('工作目录需要在本机磁盘上，不能使用网络或设备路径。')
    directory = Path(value).expanduser().resolve(strict=True)
    if not directory.is_dir() or directory == Path(directory.anchor) or str(directory).startswith(('\\\\', '//')):
        raise ValueError('请选择具体的本地文件夹，不能选择整个磁盘或网络目录。')
    return directory


def discover_codex():
    explicit = os.environ.get('AIRI_CODEX_EXE')
    if explicit:
        path = Path(explicit).expanduser().resolve()
        return path if path.is_file() and path.name.lower() == 'codex.exe' else None
    found = shutil.which('codex.exe') if os.name == 'nt' else shutil.which('codex')
    if found:
        return Path(found).resolve()
    installed = Path(os.environ.get('LOCALAPPDATA', '')) / 'OpenAI' / 'Codex' / 'bin'
    candidates = list(installed.glob('*/codex.exe')) if installed.is_dir() else []
    return max(candidates, key=lambda item: item.stat().st_mtime) if candidates else None


def friendly_failure(text, returncode):
    value = text.lower()
    if re.search(r'no session|session.*not found|thread.*not found', value):
        return 'Codex 未找到所选聊天，没有改用其他聊天。可以选择新独立任务，或在 Codex 中打开原聊天。'
    if re.search(r'not logged|unauthorized|authentication|token.*expired|sign.in|login', value):
        return 'Codex 登录需要更新，请先在本机 Codex 中完成登录。'
    if re.search(r'usage limit|rate limit|quota|credits|limit reached', value):
        return 'Codex 账号当前额度或速率受限，请稍后重试或检查账号用量。'
    if re.search(r'approval|sandbox|permission denied|access.*denied|not trusted', value):
        return '任务遇到权限或沙箱限制。未绕过审批；可调整任务或所选工作目录后再试。'
    if re.search(r'network|connection|timed.out|resolve host|dns|reconnect', value):
        return 'Codex 在线连接未完成，请检查网络后重试。'
    return f'Codex 未完成任务（退出码 {returncode}）。可在本机 Codex 中检查登录、网络和任务权限。'


class CodexTaskBridge:
    def __init__(self, root, data_dir=None, command_prefix=None):
        self.root = Path(root).resolve()
        self.data_dir = Path(data_dir or self.root / 'state')
        self.default_workspace = Path(os.environ.get('AIRI_CODEX_WORKSPACE', self.data_dir.parent / 'codex-workspace')).expanduser().resolve()
        self.default_workspace.mkdir(parents=True, exist_ok=True)
        self.target_thread = None
        self.target_label = '已有 AIRI 聊天'
        self.related_write_roots = []
        # This small local file contains preferences only, never authentication data.
        try:
            config = json.loads((self.data_dir / 'codex-preferences.json').read_text(encoding='utf-8-sig'))
            self.default_workspace = local_directory(config.get('defaultWorkspace', str(self.default_workspace)))
            if UUID.fullmatch(str(config.get('targetThreadId', ''))):
                self.target_thread = config['targetThreadId']
            if isinstance(config.get('targetThreadLabel'), str):
                self.target_label = config['targetThreadLabel'][:120]
            roots = config.get('relatedWriteRoots', [])
            if isinstance(roots, list) and len(roots) <= 4:
                self.related_write_roots = [local_directory(value) for value in roots]
        except (OSError, ValueError, TypeError):
            pass
        self._test_prefix = command_prefix
        self.lock = threading.RLock()
        self.jobs = {}
        self.processes = {}
        self.status_cache = None
        self.status_at = 0.0

    def prefix(self):
        if self._test_prefix is not None:
            return list(self._test_prefix)
        exe = discover_codex()
        if not exe:
            raise ValueError('本机尚未找到官方 Codex CLI。请先安装并登录 Codex。')
        return [str(exe)]

    @staticmethod
    def process_options():
        return {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}

    def status(self, refresh=False):
        with self.lock:
            if not refresh and self.status_cache is not None and time.monotonic() - self.status_at < 30:
                return copy.deepcopy(self.status_cache)
        result = {'installed': False, 'loggedIn': False, 'authMethod': None, 'version': None,
                  'defaultWorkspace': str(self.default_workspace), 'targetThreadConfigured': bool(self.target_thread),
                  'targetThreadLabel': self.target_label if self.target_thread else None,
                  'relatedWriteRoots': [str(value) for value in self.related_write_roots],
                  'relatedWriteRootsApplyTo': str(self.default_workspace),
                  'resumeValidation': 'configured; first submitted continuation not yet tested' if self.target_thread else 'not-configured',
                  'online': True, 'message': '尚未找到 Codex。', 'activeJobId': None}
        try:
            prefix = self.prefix()
            result['installed'] = True
            version = subprocess.run(prefix + ['--version'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=8, env=clean_codex_environment(), **self.process_options())
            match = re.search(r'\b\d+\.\d+\.\d+(?:[-+.][A-Za-z0-9.-]+)?', version.stdout)
            result['version'] = match.group() if match else None
            login = subprocess.run(prefix + ['login', 'status'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=8, env=clean_codex_environment(), **self.process_options())
            text = (login.stdout + login.stderr).lower()
            result['loggedIn'] = login.returncode == 0 and 'logged in' in text
            result['authMethod'] = 'chatgpt' if 'using chatgpt' in text else 'api-key' if 'api key' in text and result['loggedIn'] else None
            result['message'] = '已安装 · ChatGPT 账号已登录' if result['authMethod'] == 'chatgpt' else '已安装 · Codex 已登录' if result['loggedIn'] else '已安装 · 请先在 Codex 中登录'
        except (OSError, ValueError, subprocess.TimeoutExpired):
            result['message'] = 'Codex 状态暂时无法确认，请在本机 Codex 中检查。'
        with self.lock:
            result['activeJobId'] = next((job['id'] for job in self.jobs.values() if job['status'] not in TERMINAL), None)
            self.status_cache = copy.deepcopy(result)
            self.status_at = time.monotonic()
        return result

    def _event(self, job, kind, text):
        with self.lock:
            job['sequence'] += 1
            job['events'].append({'sequence': job['sequence'], 'type': kind, 'text': str(text)[:16000], 'at': utcnow()})
            job['events'] = job['events'][-120:]

    def snapshot(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                raise ValueError('没有找到这个 Codex 任务。')
            result = copy.deepcopy(job)
            result.pop('_stop', None)
            result['elapsedSeconds'] = round(job.get('_finished', time.monotonic()) - job['_started'], 2)
            result.pop('_started', None)
            result.pop('_finished', None)
            return result

    def start(self, task, directory, mode='read-only', target='new'):
        if not isinstance(task, str) or not task.strip() or len(task) > 4000 or len(task.encode('utf-8')) > 12000 or '\x00' in task:
            raise ValueError('请填写任务，最多 4000 字。')
        if mode not in ('read-only', 'workspace-write'):
            raise ValueError('请选择只读或允许修改工作目录。')
        if target not in ('new', 'existing') or target == 'existing' and not self.target_thread:
            raise ValueError('这个任务目标尚未配置。')
        cwd = local_directory(directory)
        prefix = self.prefix()
        with self.lock:
            if any(job['status'] not in TERMINAL for job in self.jobs.values()):
                raise ValueError('已有一个 Codex 任务在执行，请先等它完成或停止。')
            while len(self.jobs) >= 8:
                self.jobs.pop(next(iter(self.jobs)))
            job_id = secrets.token_hex(16)
            job = {'id': job_id, 'status': 'running', 'mode': mode, 'target': target, 'workspace': str(cwd),
                   'additionalWriteRoots': [str(value) for value in self.related_write_roots] if mode == 'workspace-write' and cwd == self.default_workspace else [],
                   'createdAt': utcnow(), 'finishedAt': None, 'message': '正在连接 Codex…', 'output': '',
                   'events': [], 'sequence': 0, 'exitCode': None, '_stop': False, '_started': time.monotonic()}
            self.jobs[job_id] = job
            self.status_at = 0
        # stdin carries the task. It never becomes a shell command or process-list argument.
        threading.Thread(target=self._run, args=(job, prefix, cwd, task.strip()), daemon=True).start()
        return self.snapshot(job_id)

    def _kill(self, process):
        if process.poll() is not None:
            return
        if os.name == 'nt':
            subprocess.run([str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'System32' / 'taskkill.exe'), '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def stop(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                raise ValueError('没有找到这个 Codex 任务。')
            if job['status'] in TERMINAL:
                return self.snapshot(job_id)
            job['_stop'] = True
            job['status'] = 'stopping'
            job['message'] = '正在停止这个 Codex 任务…'
            process = self.processes.get(job_id)
        if process:
            try:
                self._kill(process)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
        return self.snapshot(job_id)

    def _run(self, job, prefix, cwd, task):
        argv = prefix + ['exec', '--json', '--sandbox', job['mode'], '--skip-git-repo-check', '--color', 'never', '-C', str(cwd)]
        for directory in job['additionalWriteRoots']:
            argv += ['--add-dir', directory]
        argv += ['resume', self.target_thread, '-'] if job['target'] == 'existing' else ['--ephemeral', '-']
        stderr_parts = []
        failed = False
        completed = False
        process = None
        timer = None
        try:
            process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, encoding='utf-8', errors='replace', env=clean_codex_environment(), **self.process_options())
            with self.lock:
                self.processes[job['id']] = process
                stopped = job['_stop']
            if stopped:
                self._kill(process)
            timer = threading.Timer(MAX_TASK_SECONDS, lambda: self.stop(job['id']))
            timer.daemon = True
            timer.start()

            def drain():
                for line in process.stderr:
                    if sum(map(len, stderr_parts)) < 32000:
                        stderr_parts.append(line[:4000])
            threading.Thread(target=drain, daemon=True).start()
            process.stdin.write(task)
            process.stdin.close()
            for line in process.stdout:
                if len(line) > 1000000:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                kind = event.get('type')
                item = event.get('item') or {}
                if kind == 'turn.started':
                    self._event(job, 'progress', 'Codex 正在处理任务。')
                elif kind in ('item.started', 'item.completed'):
                    category = item.get('type')
                    if category == 'agent_message' and kind == 'item.completed':
                        text = str(item.get('text', ''))[:32000]
                        with self.lock:
                            job['output'] = (job['output'] + ('\n\n' if job['output'] else '') + text)[-MAX_OUTPUT:]
                        self._event(job, 'answer', text)
                    elif category in ('command_execution', 'file_change', 'mcp_tool_call', 'web_search'):
                        label = {'command_execution': '工作目录命令', 'file_change': '文件修改', 'mcp_tool_call': '工具调用', 'web_search': '网页检索'}[category]
                        self._event(job, 'progress', label + ('正在执行…' if kind == 'item.started' else '已完成。'))
                elif kind == 'turn.completed':
                    completed = True
                elif kind in ('error', 'turn.failed'):
                    failed = True
                    # Error text is classified locally; raw account/config/environment diagnostics are not exposed.
                    if sum(map(len, stderr_parts)) < 32000:
                        stderr_parts.append(str(event.get('message') or event.get('error', ''))[:4000])
            returncode = process.wait()
            with self.lock:
                job['exitCode'] = returncode
                job['status'] = 'stopped' if job['_stop'] else 'success' if returncode == 0 and completed and not failed else 'failed'
                job['message'] = '任务已停止。' if job['_stop'] else 'Codex 任务已完成。' if job['status'] == 'success' else friendly_failure(''.join(stderr_parts), returncode)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            with self.lock:
                job['status'] = 'stopped' if job['_stop'] else 'failed'
                job['message'] = '任务已停止。' if job['_stop'] else friendly_failure(type(error).__name__, -1)
        finally:
            if timer:
                timer.cancel()
            if process and process.poll() is None:
                try:
                    self._kill(process)
                except (OSError, subprocess.SubprocessError):
                    process.kill()
            with self.lock:
                job['finishedAt'] = utcnow()
                job['_finished'] = time.monotonic()
                self.processes.pop(job['id'], None)
                self.status_at = 0

    def close(self):
        with self.lock:
            active = [job['id'] for job in self.jobs.values() if job['status'] not in TERMINAL]
        for job_id in active:
            self.stop(job_id)
