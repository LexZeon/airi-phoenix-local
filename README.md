# AIRI Character Forge · 角色工具与验证方法

把完整 ZIP 交给自己的 AI agent，按需制作人设、Live2D 绑定和表情、原创合成语音与 AIRI 角色包。通用程序由 JSON 驱动，附可运行的原创机器人例子、Skill 和可选 MCP；菲欧妮是制作案例，不是唯一支持的角色。

仓库主要发布**经过验证、有用且可复用的路径、方法和工具**，说明适用条件、验证与限制。先看[已验证操作手册](docs/verified-paths.md)；调试经历只提炼有效结论和必要陷阱，未完成项单列。

**先读 [START_HERE.md](START_HERE.md)。** Skill 名为 `$airi-character-forge`，入口为根目录 [SKILL.md](SKILL.md)。

[下载单个完整工具 ZIP](https://github.com/LexZeon/airi-phoenix-local/raw/refs/heads/main/dist/airi-character-forge-0.2.3.zip)。解压后保留全部目录；它包含代码、提示词、原创示例与语音样例，外部软件／权重需按说明另行准备。

| 模块 | 已有内容与实际状态 |
| --- | --- |
| 通用 Live2D 程序 | 真正 MOC3/model3/纹理/exp3 导出；严格 schema、引用检查和外部 Core 验证；原创 robot/DeskBot 可复现 |
| agent 接口 | CLI JSON、Skill/提示词、legacy MCP 2025-11-25 stdio；不依赖固定 AI 账户 |
| 菲欧妮人设与表情 | 官方出处、原创人设/对话规则、12 个精确表情名；可导出 AIRI/CCv3/V2 卡 |
| 聊天贴纸／表情包 | 来源查询、静态PNG制备、真实store导入helper及5+5测试通过；9个本机官方帧制备通过，真实store导入/持久化/设置/缩略图已通过（9新增+12默认，启用50%）；真实聊天选图/显示另验；不带图片 |
| 语音 | Qwen3-TTS 1.7B CustomVoice 内置 Serena + 三种原创风格；真实 WAV/MP3/API/队列和离线请求层验证通过；可选省输出别名与独立Windows慧慧adapter均有合成输入实测，默认保留 |
| 常服 Live2D 案例 | 本机官图原像素保真模型：14 drawable、19 实绑参数、12 不同表情，Core 133 组合及实际 AIRI WebGL 离屏通过；中性 RGBA 与原图逐像素一致 |
| 当前角色交付分工 | 三张独立卡：官图2D（实际桌面已可见，已在app注册12表情，完整可见控制/语音联合另验）、站姿2D（参考脸候选007通过135 Core组合、29＋45实际WebGL帧和33项检查，主app已导入，活动原生视觉检查/用户最终接受另验）、用户自有3D（本机前台显示已验证，模型不公开） |
| 实际接卡／SDK观察 | 用户自有PMX ZIP经真实Pinia注册并激活；SDK合成文本完成已观察，TTS全局计数变化未精确关联（因果INCONCLUSIVE），自然3D待机已接入并可见；物理麦克风/声卡全测另验 |
| 尚未完成 | 真实聊天选贴纸、完整物理声链、角色最终视觉接受及云端TTS候选多样本比较；阿里云3.1已有一次固定短句连通，本地HTTP候选与控制台证据已有实测，实际选择依用户配置 |

官方图片、官图派生纹理/MOC3 包、官方 MMD 包、Core、模型权重和用户配置都不在公开下载中。`examples/phoenix/rig-project.recipe.json`只保留坐标和参数配方，不能在缺少本地来源文件时直接构建；可直接构建的例子是 robot 和 DeskBot。

## 快速试用

Python 3.10+ 和 Pillow 可构建；验证另需 Node 与合法取得的 Cubism Core。

```text
python -m pip install -r rig-tools/requirements.txt
python rig-tools/rig.py init --out work/robot --name MyRobot --json
python rig-tools/rig.py build --project work/robot/project.json --out work/robot/build-001 --json
python rig-tools/rig.py validate --model work/robot/build-001/MyRobot.model3.json --core-file /path/to/existing/Core.js --json
```

独立 [DeskBot 例子](examples/deskbot/README.md)还有可重建的 Idle/Demo motion3。通用构建器不编排动作、不输出 `.cmo3`，也不承诺任意单张图能自动变成完整高质量模型。程序接收已准备的透明图层或 atlas；agent 用自己可用的图像工具准备语义补绘，保留出处和提示词。

## 按模块继续

- [Live2D CLI 与字段](rig-tools/README.txt)、[项目 schema](rig-tools/project.schema.json)、[MCP](docs/agent-api.md)。
- [人设/卡与真实 ACT 表情](character-tools/README.md)、[菲欧妮设定/表情来源](examples/phoenix/sources.json)。
- [本地语音、样例和延迟](voice/README.md)：9945 `/v1/`，默认 `phoenix-qwen3-tts-local` / `phoenix-soft`；约 4.52 GB 官方权重单独获取，批处理语音需等待整句生成。
- [语音与 AIRI 接入提示词](prompts/voice-and-airi.md)、[完整制作记录](docs/process-log.md)、[权利边界](RIGHTS.md)。
- [真实3D接卡与SDK文本观察](airi-integration/README.md)、[聊天贴纸制备/导入工具](sticker-tools/README.md)。

Windows on ARM 的本机部署曾复用已有 Qwen3.5 9B、SenseVoice 和创作环境。公开包提供路径可配置的启动模板，不包含硬编码用户路径或已登录应用状态；接入既有 AIRI 卡和聊天前先按说明备份/选择目标。

原创程序、文档、提示词和机器人素材为 MIT；`py-moc3`保留原 MIT 通知。角色 IP、官方素材、Core、语音模型及各自权利单独处理。本项目是非官方同人技术记录，与 HoYoverse、Live2D 或 AIRI 没有隶属和背书关系。

用户要求本聊天的全部 AIRI 配置、修改与调试持续脱敏记录到 GitHub，约定已写入 [AGENTS.md](AGENTS.md)和[记录工作流](docs/airi-change-recording.md)。

[Windows四模块控制台脱敏模板](control-center/README.md)保留实用版25API/18交互UI/7只读UI结果，并新增发布副本8项隔离HTTP与配置备份验收。它需要已有wrapper/服务，不是通用安装器；完整wrapper快照见下方；目标功能验收按层记录。

[原创MMD待机工具](mmd-tools/README.md)通过原生VMD解析与独立实际MMDScene渲染，动作已实际导入主app；不带官模/贴图/第三方动作。[阶段延迟探针](diagnostics/README.md)已有固定输入实测，候选先测后选；默认配置保留。

[离线 wrapper 与一键启动模板](airi-integration/offline-shell/SETUP.md)保留正常 AIRI main/renderer，并记录已实测 Windows UTF-8 与进程身份修复；[9942共享语音](shared-speech/README.md)复用现有 SenseVoice 和小型 Melo，模型、Python 环境和所有真实 settings 均在包外。

[实测语音选择表](docs/speech-options.md)对照Serena默认/可选省输出模式、Melo、系统慧慧和未测云端；保持默认，选择权留给使用者。

[文字响应审计](diagnostics/llm-latency-audit.md)核实9B已关闭思考，并实测短输入与约12K未缓存合成输入的读取延迟；不把短prompt结果冒充实际角色对话速度。[屏幕权限方法](docs/screen-access-off.md)使已有按钮与后台助手统一关闭，清除旧屏幕摘要并阻止晚到结果；5项worker、15项生产Proxy逻辑及真实SDK检查通过，原生按钮开关后79.07秒无新发布。[Windows登录自启](docs/windows-sign-in.md)复用原一键启动器；[参考脸QA](docs/live2d-face-qa-lessons.md)说明数值对齐与人物自然度的区别。

[MMD构图保存工具](airi-integration/offline-shell/MMD-CAMERA-PERSISTENCE.md)按模型区分主窗/设置预览，保存拖动、缩放和视角；V2通过41项VM、compiled生命周期与真实Three/Vue检查，原生重启已恢复选定近景并核对可见画幅。它只补丁已有编译资产，不附AIRI第三方资产或私人视角种子。

[本机Codex任务入口](control-center/codex-task-assistant-verified.md)复用官方CLI已登录的ChatGPT账号，明确点击才提交任务，附9项离线回归和一次真实只读合成文件验证；已有任务续写未测。[可选在线文字聊天](online-chat/README.md)另提供9948纯文字adapter，保留本地选项；真实AIRI SDK合成文字路径6.461秒通过，直接图片/工具调用与逐token流式不支持，私人任务ID与登录状态不附包。

[可选阿里云语音](voice/aliyun-tts/README.md)已加入角色声音列表与本机密钥/音色/试听面板；25项adapter、14项控制台隔离检查及真实Windows owned服务启停通过。0.2.3修复含点号工作空间Key与已完成SSE的已知WAV占位头；一次真实3.1固定短句测得首音频1.792s、完整3.28s WAV等待2.375s。仅单次API连通，不是实际AIRI出声或物理声链基准；私人凭证和音频不发布。

[0.2.3实际应用与启动](voice/aliyun-tts/verification-airi-startup-live.json)另已读回三卡Aliyun speech、保留本地聊天/识别、3D/idle与原生“正在听”状态；9949第二短句HTTP200，完整WAV2.184s。它没有播放音频；用户实聊/物理声链与持续稳定性仍需体验，未把启动就绪冒称全功能通过。
