# Windows 本机 AIRI 四模块配置台

提供聊天、视觉、ASR、TTS的明确选择与本机OpenAI-compatible/Ollama兼容服务设置。
选择保存与真正应用分开；应用保留其他配置/角色并生成原子备份，启动操作调用固定现有launcher，
不会下载或安装模型。UI明确区分“配置已保存”和“AIRI实际已加载当前revision”。

这是本机实用版的**参数化脱敏部署模板**，不含个人settings、token、state、日志、模型目录、
截图或浏览器profile。历史本机25API、18交互UI、7最终只读UI检查见
[脱敏汇总](verification-summary.json)；发布副本另用隔离fixture验证参数化、配置保留与备份。
不把原机器的整体验收直接当成另一台机器的部署成功。

## 适用条件与参数

Windows、PowerShell5.1和可用Python3.10+；使用Windows `msvcrt`文件锁。
需要一套已有AIRI离线wrapper：它消费 `offline-settings.json`中的providers/modules/storage/
character.modulesOverride和revision，并提供预期health端点。此包首版不包含那台机器的
完整wrapper、LLM/ASR启动器或个人配置，控制台本身不是通用AIRI安装器。
源码字段/模块契约可复用；换AIRI版本或wrapper后需要重新做目标应用验收。

先在自己的进程或启动脚本中配置环境变量，不改全局PATH：

```powershell
$env:AIRI_PYTHON = 'C:\path\to\existing\python.exe'
$env:AIRI_COMPANIONS_ROOT = 'C:\path\to\your\AI-Companions'
$env:AIRI_OFFLINE_SETTINGS = 'C:\path\to\your\offline-settings.json'
$env:AIRI_MODELS_ROOT = 'C:\path\to\shared\Models'
$env:AIRI_CONTROL_DATA_DIR = 'C:\path\to\private\control-state'
& .\launchers\control-center-start.ps1
```

可选 `AIRI_WORKBENCH`指向已有27B/Ollama工作台；`AIRI_SPEECH_ROOT`和`AIRI_TTS_ROOT`指向
现有ASR/TTS服务目录；默认是部署根的runtime子目录。`AIRI_CONTROL_PORT`默认9944，
`AIRI_HARDWARE_LABEL`可写硬件简称；实时硬件数据来自CIM/nvidia-smi，不假定所有机器128GiB。
模型清单是示例部署的预设，可修改 `airi_catalog.py`和`profiles.py`适配现有服务，不爬取创作模型库。
预设9B聊天与视觉复用同一回环服务，不声称重复加载两份权重。

本包的 `launchers/airi-select-profile.ps1`消费控制台自己的受管理请求文件，再调用
`AIRI_COMPANIONS_ROOT/launchers`中已有的 `airi-stop.ps1`、`airi-start.ps1`及必要模型服务启动器。
这些未存在时会失败并说明，不会静默安装。只有已满足依赖并确认目标wrapper契约，才使用
“应用并启动/重启”按钮；单纯保存偏好不触碰AIRI设置。

停止仅本控制台：

```powershell
& .\launchers\control-center-stop.ps1
```

它核对本实例state、Python进程命令行、health PID，再通过同源CSRF shutdown关闭控制台，
保留AIRI和模型服务。所有私有状态留在 `AIRI_CONTROL_DATA_DIR`，不要提交到GitHub。

## 能力边界

回环绑定、Host/Origin/CSRF限制、固定命令数组、URL限制和本地API列表检查已在实用版测试。
模型列表能连接不证明聊天/视觉/音频格式都被服务实现；真实能力和实际播放仍须分别测试。
当前控制台不承包聊天贴纸/表情包设置，也不靠人设提示自动授予看屏幕/麦克风权限。
完整wrapper、最新桌面模型位置/12表情/TTS联合验收另行记录，未提前标为全功能通过。

多卡模块切换已补充：应用新的聊天/视觉/ASR/TTS选择时同步主卡及additionalCharacters的modulesOverride和selectionRevision，保留每张卡的modelZip与activate。三卡隔离回归见[verification-multi-card.json](verification-multi-card.json)，发布副本8项fixture测试也覆盖该路径，未触碰实际设置。

## 已验证的两个可选速度项

最终目录提供 `qwen-efficient` 与 `sapi-huihui`，工具初始默认是 `qwen-soft`，可由使用者明确选择切换。新UI实际显示Serena同句6.08s与慧慧接口中位约0.06s，已验证切换选择框/证据展示后恢复默认，没有点击应用、自动试听或横向溢出；不把这份UI观察当成扬声器回放。见 [临时三卡映射](verification-speed-options.json)、[接口与样例](verification-speed-ui-api.json)、[真实浏览器](verification-speed-browser.json)。

使用SAPI前将 [voice/windows-sapi](../voice/windows-sapi/README.md) 源码部署到 `<base>/runtime/airi-sapi`，或显式设置 `AIRI_SAPI_ROOT`。内部 `ensure_token()` 只在配置应用时取得本机key；catalog/preferences不返回它。启动模板会检查全局、主角色和所有附加卡的speech provider，需要9947才启动SAPI；默认完整停止只终止经严格身份检查的owned服务，KeepServices保留。无SAPI部署时不要把该选项视为已安装。

Serena优化版的UI选择、实际voice ID和原模式回退步骤见[启用/回退方法](../docs/speech-options.md#在控制台启用-serena-优化版与回退)。仅“记住选择”不会应用；需要应用并启动/重启后再核对全局和每卡speech。

[实际优化版启用验证](verification-efficient-activation.json)已确认三卡override和分层运行时读回/就绪，控制台偏好同步。未执行本次启用后的实际回退、物理首声计时或角色视觉验收；这些不从设置成功推断。

## 复用本机 Codex 登录的任务入口

[Codex任务助手方法](codex-task-assistant-verified.md)附独立 `codex_bridge.py`、页面模块和8项离线子进程/API测试。它复用官方CLI及用户已有登录；不读取/复制auth或cookie，不替换AIRI日常聊天模型，也不自动转发其对话或屏幕。只有用户提交任务后才在线运行，默认只读；目录、目标和写入模式在表单里明确选择。

需要已有可用的官方CLI；可用 `AIRI_CODEX_EXE` 指定已有executable，用 `AIRI_CODEX_WORKSPACE` 指定默认本地文件夹。任务正文从stdin送入，用户配置的CLI模型默认值保留。子进程环境保留系统/登录发现及代理变量，排除外层桌面任务的临时工具管道和身份，避免错误继承当前agent会话。

默认创建独立临时任务。若使用者明确要续接某个已有任务，可在私有 `AIRI_CONTROL_DATA_DIR/codex-preferences.json` 设置自己的 `defaultWorkspace`、`targetThreadId`、`targetThreadLabel`；UUID必须由可信本机任务元数据取得，不猜测，不公开。元数据读取与真实续写是不同验证：本次只验证了指定任务元数据；实际追加必须由使用者明确提交，尚未测试。不要把本仓库聊天历史/目录当作自己的默认目标。

控制台的任务结果仅在有界内存中保留；外部CLI本身的本地状态和账户行为另循其机制。`state/`与默认`codex-workspace/`都不进入Git和ZIP。窗口关闭会取消本控制台跟踪的活动Codex子进程，不停止AIRI或模型。此功能不是ChatGPT桌面窗口的UI自动化。

[生产页面与回退报告](verification-online-console-production.json)记录原生页面实际显示在线选项、Codex登录/已有目标和工作目录表单，按钮可用；在线下拉展示后恢复本地9B。运行配置最终为9B＋Windows慧慧，屏幕观察关闭、3D近景恢复、9948适配器停止；没有把Serena优化别名误当当前声音。Serena优化仍是可选项。已有任务实际追加保持未测；本页可见/已登录不等于已发送任务。视觉模型“就绪”与屏幕“观察已关闭”现在分别显示。

## 可选阿里云语音

[配置与试听方法](aliyun-console-verified.md)新增“阿里云 · 在线语音”与本机密码框、地域/音色、高级情绪语音和测速。按[部署说明](../voice/aliyun-tts/README.md)先安装标准库adapter到 `<base>/runtime/airi-aliyun-tts`。保存不切换当前声音；试听成功后先选入草稿，再明确应用/重启。真实Key仅以当前用户DPAPI密文保存，AIRI只拿本地token。25项adapter与14项console隔离测试通过；云端请求、速度、音质和实际AIRI出声保持未测。
