# 把这个完整包交给自己的 AI agent

解压 ZIP 后，把整个 `airi-character-forge` 目录交给有本地读写和命令执行能力的 agent。支持 Skills 的工具读取根目录 `SKILL.md`；普通编码 agent 也能直接读说明和调用 CLI。程序不依赖 Codex 私有工具或固定绘图服务。

可直接复制的任务：

> 请读取本包 SKILL.md，根据我的角色资料制作或修改 AIRI 伙伴。先检查现成 Live2D/3D 参考及许可，复用已有模型与环境；按需处理人设、图层、绑定、表情、语音和 AIRI 接入。使用包内程序验证，保存项目、提示词、出处、报告和未完成项。角色：【填写】；本次范围：【完整角色／只改绑定／只配声音／只接 AIRI】；已有资产和软件：【路径】。

## 先运行可复现示例

Python 3.10+ 和 Pillow 用于构建；Node 与用户合法取得的 Core 用于验证。安装到自己的项目环境。包内无 Core、权重或官方角色图片。

```text
python -m pip install -r rig-tools/requirements.txt
python rig-tools/rig.py init --out work/my-robot --name MyRobot --json
python rig-tools/rig.py inspect --project work/my-robot/project.json --json
python rig-tools/rig.py build --project work/my-robot/project.json --out work/my-robot/build-001 --json
python rig-tools/rig.py validate --model work/my-robot/build-001/MyRobot.model3.json --core-file /path/to/existing/Core.js --node-executable node --json
```

全部路径应换成自己的路径。机器返回的 `ok`、`stage`、`code`、`outputs` 和 `summary` 是结果依据；缺少 Core 时不能称为验证通过。构建器输出 MOC3、model3、纹理和表达式，不输出 Cubism Editor 的 `.cmo3`。

[构建器说明](rig-tools/README.txt)及 [JSON schema](rig-tools/project.schema.json)描述完整字段。[DeskBot](examples/deskbot/README.md)是独立改编的原创机器人例子，并提供 Idle/Demo 的后处理 motion3 脚本；通用项目 schema 本身没有动作编排字段。

## 按需使用其他模块

- **人设和卡**：[character-tools](character-tools/README.md)导出 AIRI、CCv3、SillyTavern V2。`examples/phoenix`有设定、12 表情出处、原创人设和制作配方，不附角色图片/模型；它不是开箱即用的菲欧妮模型包。
- **声音**：[voice](voice/README.md)提供本地 Qwen3-TTS CustomVoice Serena 与三种原创风格，附实际合成样例；无声优克隆、无权重。约 4.52 GB 权重需单独获取，可复用已有匹配文件。默认服务是回环 9945。
- **接入 AIRI**：[语音与接入提示词](prompts/voice-and-airi.md)和 [角色导出说明](character-tools/README.md)。卡导入不自动安装推理服务、Core 或 ASR。
- **MCP**：[docs/agent-api.md](docs/agent-api.md)说明可选 stdio 适配器。CLI 不要求 MCP。协议版本是明确的 legacy 2025-11-25，不能称为已支持任何客户端的新协议。

## 安装 Skill 或直接使用

支持 Skills 的工具：保留完整目录并将文件夹命名为 `airi-character-forge`，放入该工具的 Skills 目录，调用 `$airi-character-forge`。其他 agent 直接把本目录作为工作区；`AGENTS.md`保留项目约定。不要只复制 SKILL.md 而漏掉程序、资源和许可证。

agent 用自己有权限的图像工具做语义补绘；构建器只做确定性的裁切、显式蒙版合成、纹理 atlas 和参数绑定。单张图片不能自动保证变成高质量的全动作角色。已有官方立绘的保真制作应保留姿势与轮廓，仅补必要小区域，不能默默重画成另一张脸。

[RIGHTS.md](RIGHTS.md)分别说明程序、角色 IP、官方媒体、Core 和语音模型的权利；[制作记录](docs/process-log.md)列出已验证和待完成状态。发布时不附个人聊天、私人截图、登录状态或密钥。
