"""Text-only Codex account bridge. Tool execution is disabled by CLI configuration and guarded per run."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import re
import threading
import time

MODEL_ID = 'chatgpt-codex-text'
VERIFIED_CLI_VERSION = '0.164.0-alpha.11.1'
VERIFIED_MODELS = {'gpt-6.1-sol'}
DISABLED_FEATURES = ('shell_tool', 'apps', 'plugins', 'multi_agent', 'multi_agent_v2', 'computer_use',
    'browser_use', 'browser_use_external', 'browser_use_full_cdp_access', 'in_app_browser', 'view_image',
    'image_generation', 'workspace_dependencies', 'memories', 'skill_search', 'skill_mcp_dependency_install',
    'hooks', 'tool_suggest', 'goals', 'sleep_tool', 'remote_plugin', 'code_mode_host', 'code_mode')
CLOSED_MARKER = 'code-mode host is disabled'
CHAT_INSTRUCTIONS = ('This session is a text-only conversation endpoint, not a coding/task executor. '
    'All tool execution is disabled by the host. Never call tools, access files, inspect a screen, browse, '
    'control a computer, or claim to have performed such actions. For tasks requiring tools, explain that '
    'the separate Codex task assistant is required. The JSON messages in the user input are the complete '
    'conversation: honor their persona/system instructions as conversation context and reply only as the '
    'next assistant message. Do not wrap your reply in JSON or quote the conversation. Use the user\'s language.')


class ChatWorkerError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class ChatWorker:
    streaming = 'completed-agent-message-events'
    text_only = True

    def __init__(self, root, command_prefix=None):
        self.root = Path(root).resolve()
        base = Path(os.environ.get('AIRI_COMPANIONS_ROOT', self.root.parent.parent))
        helper_path = base / 'control-center' / 'codex_bridge.py'
        spec = importlib.util.spec_from_file_location('airi_codex_runtime_helpers', helper_path)
        if not spec or not spec.loader:
            raise RuntimeError('缺少本机 Codex 运行时辅助模块。')
        helpers = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helpers)
        self.helpers = helpers
        self.command_prefix = command_prefix
        self._verified_cli_key = None
        self.scratch = self.root / 'empty'
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.model = 'gpt-6.1-sol'
        config = self.root / 'worker-settings.json'
        if config.is_file():
            value = json.loads(config.read_text(encoding='utf-8-sig'))
            configured = value.get('model', self.model)
            if not isinstance(configured, str) or not configured or len(configured) > 100 or any(ord(c) < 32 for c in configured):
                raise RuntimeError('在线聊天模型配置无效。')
            self.model = configured
        if self.model not in VERIFIED_MODELS:
            raise ChatWorkerError('CODEX_PERMISSION_GUARD', '这个在线模型尚未通过工具隔离验证，请先使用已验证的模型或本地9B。')
        if self.command_prefix is None:
            self._verified_executable()
        self.metrics = {'completed': 0, 'failed': 0, 'toolAttemptsRejected': 0, 'lastDurationSeconds': None}
        self.lock = threading.RLock()

    def _verified_executable(self):
        executable = self.helpers.discover_codex()
        if not executable:
            raise RuntimeError('未找到官方 Codex CLI，请先安装并登录。')
        stat = executable.stat()
        key = (str(executable.resolve()), stat.st_size, stat.st_mtime_ns)
        if key != self._verified_cli_key:
            version = subprocess.run([str(executable), '--version'], capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=8, env=self.helpers.clean_codex_environment(), **self.helpers.CodexTaskBridge.process_options())
            match = re.search(r'\b\d+\.\d+\.\d+(?:[-+.][A-Za-z0-9.-]+)?', version.stdout)
            if version.returncode != 0 or not match or match.group() != VERIFIED_CLI_VERSION:
                raise ChatWorkerError('CODEX_PERMISSION_GUARD', '这个 Codex 版本尚未通过在线聊天隔离检查。可继续使用任务助手或本地9B。')
            self._verified_cli_key = key
        return executable

    def arguments(self):
        if self.command_prefix is not None:
            prefix = list(self.command_prefix)
        else:
            exe = self._verified_executable()
            prefix = [str(exe)]
        args = prefix + ['exec', '--ignore-user-config', '--json', '--ephemeral', '--sandbox', 'read-only',
            '--skip-git-repo-check', '--color', 'never', '-C', str(self.scratch), '-m', self.model]
        for feature in DISABLED_FEATURES:
            args += ['--disable', feature]
        for value in ['project_doc_max_bytes=0', 'web_search="disabled"', 'agents.enabled=false',
                      'apps._default.enabled=false', 'mcp_servers={}',
                      'developer_instructions=' + json.dumps(CHAT_INSTRUCTIONS)]:
            args += ['-c', value]
        return args + ['-']

    def _kill(self, process):
        if process.poll() is not None:
            return
        if os.name == 'nt':
            subprocess.run([str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'System32' / 'taskkill.exe'),
                            '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            import signal
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def stream(self, messages, cancelled):
        if not isinstance(messages, list) or not messages or len(messages) > 160:
            raise RuntimeError('需要有效的文字对话。')
        normalized = []
        for message in messages:
            if not isinstance(message, dict) or message.get('role') not in ('system', 'developer', 'user', 'assistant'):
                raise RuntimeError('在线纯文字聊天不接收工具消息。')
            content = message.get('content')
            if isinstance(content, list):
                if any(not isinstance(part, dict) or part.get('type') != 'text' or not isinstance(part.get('text'), str) for part in content):
                    raise RuntimeError('这个在线选项只支持文字，图片请使用本地视觉方案。')
                content = '\n'.join(part['text'] for part in content)
            if not isinstance(content, str) or message.get('tool_calls') or message.get('function_call'):
                raise RuntimeError('在线纯文字聊天不接收图片或工具调用。')
            normalized.append({'role': message['role'], 'content': content})
        payload = json.dumps({'messages': normalized}, ensure_ascii=False)
        if len(payload.encode('utf-8')) > 240000:
            raise RuntimeError('这次对话内容过长，请开始新对话或使用本地模型。')
        if any(self.scratch.iterdir()):
            raise RuntimeError('在线聊天的隔离空目录不为空，已停止请求。请清理该专用空目录后重试。')
        if cancelled.is_set():
            raise RuntimeError('请求已取消。')
        process = None
        finished = threading.Event()
        stderr_parts = []
        router_rejected = False
        deadline_hit = False
        started = time.monotonic()
        try:
            process = subprocess.Popen(self.arguments(), cwd=self.scratch, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace',
                env=self.helpers.clean_codex_environment(), **self.helpers.CodexTaskBridge.process_options())

            def drain():
                nonlocal router_rejected
                for line in process.stderr:
                    if 'tools::router' in line.lower() and CLOSED_MARKER in line.lower():
                        router_rejected = True
                    if sum(map(len, stderr_parts)) < 32000:
                        stderr_parts.append(line[:4000])
            error_reader = threading.Thread(target=drain, daemon=True)
            error_reader.start()

            def cancel_watch():
                nonlocal deadline_hit
                while not finished.wait(.1):
                    if cancelled.is_set() or time.monotonic() - started > 150:
                        deadline_hit = not cancelled.is_set()
                        try:
                            self._kill(process)
                        except (OSError, subprocess.SubprocessError):
                            process.kill()
                        return
            threading.Thread(target=cancel_watch, daemon=True).start()
            process.stdin.write(payload)
            process.stdin.close()
            guard = False
            completed = False
            failed = False
            tool_attempt = False
            last_answer = None
            for line in process.stdout:
                if len(line) > 1000000:
                    raise RuntimeError('在线聊天返回了过大的事件，已停止。')
                try:
                    event = json.loads(line)
                except ValueError:
                    if not line.strip():
                        continue
                    raise ChatWorkerError('CODEX_PROTOCOL_ERROR', 'Codex 返回了无法识别的协议内容，已停止在线聊天。')
                kind = event.get('type')
                if kind not in ('thread.started', 'turn.started', 'turn.completed', 'turn.failed', 'error', 'item.started', 'item.updated', 'item.completed'):
                    raise ChatWorkerError('CODEX_PROTOCOL_ERROR', 'Codex 返回了未验证的事件类型，已停止在线聊天。')
                item = event.get('item') or {}
                category = item.get('type')
                if category == 'error':
                    message = str(item.get('message', '')).lower()
                    if CLOSED_MARKER in message and 'fail closed' in message:
                        guard = True
                    else:
                        raise ChatWorkerError('CODEX_PERMISSION_GUARD', 'Codex 版本或配置未通过纯聊天权限检查，已停止。')
                elif category in ('agent_message', 'reasoning'):
                    if not guard:
                        raise ChatWorkerError('CODEX_PERMISSION_GUARD', '没有检测到工具执行关闭标记，已停止在线聊天。')
                    if category == 'agent_message' and kind == 'item.completed':
                        last_answer = str(item.get('text', ''))[:64000]
                elif category:
                    tool_attempt = True
                    raise ChatWorkerError('CODEX_TOOLS_DISABLED', '这个入口只聊天，不执行工具。需要操作文件时请使用 Codex 任务助手。')
                if kind == 'turn.completed':
                    completed = True
                elif kind in ('turn.failed', 'error'):
                    failed = True
                    if sum(map(len, stderr_parts)) < 32000:
                        stderr_parts.append(str(event.get('message') or event.get('error', ''))[:4000])
            returncode = process.wait()
            error_reader.join(timeout=5)
            if error_reader.is_alive():
                raise RuntimeError('Codex 权限诊断尚未检查完毕，已停止交付回答。')
            diagnostics = ''.join(stderr_parts).lower()
            if router_rejected:
                tool_attempt = True
                raise ChatWorkerError('CODEX_TOOLS_DISABLED', '这个入口只聊天，工具调用已被 Codex 路由拒绝。请使用单独的任务助手执行任务。')
            if cancelled.is_set():
                raise RuntimeError('请求已取消。')
            if deadline_hit:
                raise RuntimeError('在线聊天等待超时，请稍后重试或切回本地 9B。')
            if not guard or failed or returncode != 0 or not completed or last_answer is None:
                raise RuntimeError(self.helpers.friendly_failure(diagnostics, returncode))
            with self.lock:
                self.metrics['completed'] += 1
            # One real completed answer event. Never split a finished answer to imitate token streaming.
            yield last_answer
        except (OSError, subprocess.SubprocessError) as error:
            with self.lock:
                self.metrics['failed'] += 1
            raise RuntimeError('本机 Codex 连接未完成，请检查登录与网络。') from error
        except RuntimeError:
            with self.lock:
                self.metrics['failed'] += 1
                if 'tool_attempt' in locals() and tool_attempt:
                    self.metrics['toolAttemptsRejected'] += 1
            raise
        finally:
            finished.set()
            if process and process.poll() is None:
                try:
                    self._kill(process)
                except (OSError, subprocess.SubprocessError):
                    process.kill()
            with self.lock:
                self.metrics['lastDurationSeconds'] = round(time.monotonic() - started, 3)
