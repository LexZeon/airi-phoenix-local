# ChatGPT 账号的可选文字聊天适配器

这条路径复用用户已经登录的官方 Codex CLI，为 AIRI 提供本机回环 `9948/v1/chat/completions`。它不同于桌面 ChatGPT 窗口，也不同于控制台的[任务助手](../control-center/codex-task-assistant-verified.md)：这里仅聊天，任务入口才处理使用者主动交付的文件工作。

选择在线聊天后，AIRI 请求中的角色、历史和其他文字上下文会在线处理。适配器不接收直接图片、工具调用或工具消息，不是完整 OpenAI API，也不是离线模型。已有本地 9B、视觉、识别和语音选项保留；开启应用不等于选择在线聊天，启动屏幕观察仍默认关闭。

## 已验证的前提与部署

- 已安装、已登录的官方 CLI **0.164.0-alpha.11.1**；worker严格核对该版本。更换版本后须重新核对工具路由和配置契约，未验证版本会拒绝请求。
- 受测在线模型为 **gpt-6.1-sol**。它由文字 worker 显式选择；控制台的独立任务助手则继承用户自己的 CLI 配置。不要把两者的默认值混为一谈。
- 已有 Python 3 标准库运行环境、正常工作的 AIRI/wrapper 和本仓库控制台辅助模块；不下载模型、CLI、登录状态或权重。

将本目录的源码和 PowerShell 部署到 `<base>/runtime/airi-codex-chat/`，将 `control-center/codex_bridge.py` 放到 `<base>/control-center/`。`AIRI_COMPANIONS_ROOT`可指定base，`AIRI_CODEX_EXE`可指定已安装CLI，`AIRI_CODEX_CHAT_PYTHON`可指定现有Python。运行 `start.ps1` 后可用 `health.ps1`核对本机服务，`stop.ps1`只停止通过进程身份检查的本适配器。

`api-token.txt`、`server-state.json`、可选`worker-settings.json`、`logs/`与隔离`empty/`均为本地状态，不提交到Git或ZIP。本机Bearer token由适配器生成，不是ChatGPT账户token；它不从HTTP状态/控制台偏好返回。`/health`只是进程状态，明确不代表云端连通已经检查。

控制台增加了“ChatGPT账号 · 在线聊天”选项，只允许用于聊天。应用选择时为全局及受管理卡同步该provider，视觉/ASR/TTS不替换；一键启动仅在实际选中9948 provider时启动此服务，切回本地时安全停止它。公开控制台保留 `AIRI_CODEX_CHAT_ROOT`路径覆盖和自己的状态目录/端口。

## 文字边界与真实交付时刻

worker在专用空目录运行CLI，忽略用户配置并关闭代码/工具执行相关功能，同时要求每次运行出现经过验证的关闭路由诊断。工具事件、路由拒绝、未知诊断或失败会阻止交付回答；不会让聊天提示词变成电脑控制任务。部分工具定义仍可能存在于CLI内部schema，**不声称schema已全部移除**。任务助手具有另一套明确权限选择，不复用此文字worker。

CLI目前在完整 `agent_message`完成时交付文本。HTTP支持SSE，但不会把已经完成的答案拆开假装逐token生成；`token_streaming=false`。一次合成角色问候测到首SSE role约0.0156秒、首真实内容约5.953秒（也是完整答案事件）。首role包不是首文字，单次短问候也不能代表实际AIRI长历史速度。

AIRI的`llm` store只返回公开action，没有暴露其内部兼容Map。wrapper通过实际 `llm.$onAction('stream')`，仅对确切9948回环endpoint与`chatgpt-codex-text` alias注入 `supportsTools:false / taskTools:[] / tools:[]`，防止AIRI把工具请求交给纯文字API。离线9B和其他endpoint不受该hook影响。见[bootstrap](../airi-integration/offline-shell/online-chat-bootstrap.js)及7项无私有Map形状的[测试](../airi-integration/offline-shell/verification/verify-online-chat-bootstrap.cjs)。真实AIRI provider路径须由独立SDK探针另验，不能用临时HTTP测试代替。

## 可复测的检查

```text
python online-chat/verify_worker.py
python online-chat/verify_http.py
python control-center/verify_codex_bridge.py
python control-center/verify_online_choice.py
```

公开副本已运行：文字worker6组离线子进程检查、13项临时HTTP检查、任务桥9项及在线选择9项。它们使用fake CLI或worker、临时设置和端口，不会提交云任务、读取真实AIRI设置、操作麦克风或启动生产9948。worker测试的helper源查找按本仓库布局映射；生产worker的部署布局不变。

实际CLI连通、合成persona/SSE、生产服务启停以及真实AIRI SDK观察分别保留自己的证据边界。隔离/ephemeral不等于外部CLI绝不产生运行时本地元数据；本适配器不保存对话正文、Codex auth或原始stderr。使用自己的账号及额度，没有额外API key并不意味着调用不消耗账户用量。

生产服务的[真实启停报告](verification-lifecycle-live.json)验证首次ready、重复启动复用同一进程/实例和安全停止，其他监听进程及AIRI设置不变，无云调用。修正公开action hook后，[真实AIRI SDK合成观察](../airi-integration/offline-shell/verification/online-sdk-text-verification.json)在6.461秒收到自身binding的message/complete各1，预期短语匹配；同时gateway请求/完成计数各增加1、失败0。全局计数仍仅是并发观察，SDK完成不是token首字，更不是麦克风到扬声器测量。此前访问内部Map的方案在真实store中不可用，不作为可复用方法保留。

[生产控制台/回退验收](../control-center/verification-online-console-production.json)已确认可见在线选项与任务入口，并恢复实际运行的本地9B＋系统慧慧，9948服务停止，屏幕保持关闭且3D近景恢复。代码提供在线选项，不把它设置为使用者必须采用的默认方案。
