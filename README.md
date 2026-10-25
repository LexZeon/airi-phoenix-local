# AIRI Character Forge · 菲欧妮本地伙伴制作记录

把完整 ZIP 交给自己的 AI agent，按需制作人设、Live2D 绑定和表情、原创合成语音与 AIRI 角色包。通用程序由 JSON 驱动，附可运行的原创机器人例子、Skill 和可选 MCP；菲欧妮是制作案例，不是唯一支持的角色。

仓库主要发布**经过验证、有用且可复用的路径、方法和工具**，说明适用条件、验证与限制。先看[已验证操作手册](docs/verified-paths.md)；调试经历只提炼有效结论和必要陷阱，未完成项单列。

**先读 [START_HERE.md](START_HERE.md)。** Skill 名为 `$airi-character-forge`，入口为根目录 [SKILL.md](SKILL.md)。

[下载单个完整工具 ZIP](https://github.com/LexZeon/airi-phoenix-local/raw/refs/heads/main/dist/airi-character-forge-0.2.0.zip)。解压后保留全部目录；它包含代码、提示词、原创示例与语音样例，外部软件／权重需按说明另行准备。

| 模块 | 已有内容与实际状态 |
| --- | --- |
| 通用 Live2D 程序 | 真正 MOC3/model3/纹理/exp3 导出；严格 schema、引用检查和外部 Core 验证；原创 robot/DeskBot 可复现 |
| agent 接口 | CLI JSON、Skill/提示词、legacy MCP 2025-11-25 stdio；不依赖固定 AI 账户 |
| 菲欧妮人设与表情 | 官方出处、原创人设/对话规则、12 个精确表情名；可导出 AIRI/CCv3/V2 卡 |
| 聊天贴纸／表情包 | 与Live2D面部表情分开的AIRI配置；官方来源、获取代码和实际聊天显示仍在单独接入中 |
| 语音 | Qwen3-TTS 1.7B CustomVoice 内置 Serena + 三种原创风格；真实 WAV/MP3/API/队列和离线请求层验证通过 |
| 常服 Live2D 案例 | 本机官图原像素保真模型：14 drawable、19 实绑参数、12 不同表情，Core 133 组合及实际 AIRI WebGL 离屏通过；中性 RGBA 与原图逐像素一致 |
| 当前角色交付分工 | 三张独立卡：官图2D（实际桌面已可见，位置/12表情与语音联合待验）、站姿2D（继续制作）、用户自有3D（本机前台显示已验证，模型不公开） |
| 尚未完成 | 三卡配置与完整功能联合验收、站姿2D和两套时装制作；现有任务完成后再测端到端语音延迟 |

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

Windows on ARM 的本机部署曾复用已有 Qwen3.5 9B、SenseVoice 和创作环境。这个公开包不包含其他电脑的启动器、硬编码用户路径或已登录应用状态，也不自动接管现有 AIRI 卡和聊天。

原创程序、文档、提示词和机器人素材为 MIT；`py-moc3`保留原 MIT 通知。角色 IP、官方素材、Core、语音模型及各自权利单独处理。本项目是非官方同人技术记录，与 HoYoverse、Live2D 或 AIRI 没有隶属和背书关系。

用户要求本聊天的全部 AIRI 配置、修改与调试持续脱敏记录到 GitHub，约定已写入 [AGENTS.md](AGENTS.md)和[记录工作流](docs/airi-change-recording.md)。

[Windows四模块控制台脱敏模板](control-center/README.md)保留实用版25API/18交互UI/7只读UI结果，并新增发布副本7项隔离HTTP与配置备份验收。它需要已有wrapper/服务，不是通用安装器；完整wrapper快照和目标功能验收后续单独收录。
