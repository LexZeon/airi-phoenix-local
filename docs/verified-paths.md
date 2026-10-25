# 已验证、可以复用的路径

这里是项目主操作手册。每条方法给出适用条件、可执行入口、实际验证和限制。
源码、Skill、提示词和数值报告随包；未完成项在文末单列。

## 从透明图层构建真正 Live2D

适用于：已有合法可用的 RGBA PNG 图层或 atlas，agent 能按项目 JSON 写明位置、网格、参数和表情。
依赖：Python 3.10+、Pillow；二进制/几何验证另需 Node 和用户合法取得的现有 Cubism Core。

```text
python -m pip install -r rig-tools/requirements.txt
python rig-tools/rig.py init --out work/robot --name MyRobot --json
python rig-tools/rig.py inspect --project work/robot/project.json --json
python rig-tools/rig.py build --project work/robot/project.json --out work/robot/build-001 --json
python rig-tools/rig.py validate --model work/robot/build-001/MyRobot.model3.json --core-file /path/to/existing/Core.js --node-executable node --json
```

正常结果是各阶段 `ok:true`、`code:OK`，以及真实 MOC3/model3/PNG/exp3/ZIP。外部 Core 不随包。
实际原创 robot 经过 MCP inspect→build→Core validate，6网格/6参数/3表情/72几何组合通过。
独立 [DeskBot](../examples/deskbot/README.md)用另一份 JSON 配置验证8网格/7参数/4表情/77组合，
左右blink、口型和浅头动分别绑定，并有可重建的Idle/Demo motion3后处理。

本机测试使用 Core5.0 与已有 AIRI Pixi/Cubism WebGL。通用 `render`入口可借用合法已有的
AIRI编译输出、Electron和Core生成隔离离屏证明；见[构建器说明](../rig-tools/README.txt)。
这依赖对应AIRI bundle导出，换版本应重新验证。实际[原创robot渲染](images/robot-preview.png)
不包含官方角色像素。二进制/几何PASS不证明纹理方向、面部美术或目标桌面已验收。

限制：不会从任意单张图自动理解和绘制所有隐藏部位，不输出Cubism Editor `.cmo3`。
schema不编排动作；DeskBot明确以项目脚本添加motion3。验证器需要自家`build-manifest.json`，
不能拿它无条件认证任意下载的第三方model3。源码中的六项回归还验证未知schema字段、
缺纹理/表达式/动作/音频、坏PNG、越界路径与只读Core行为；失败保持exit2/4。

## 保真拆脸与独立跟瞳

适用于：许可允许相应本地编辑的原图，需要保留原姿势、轮廓和服装。
agent先用自己的图像工具得到小范围皮肤/眼白underlay，再以`source_overlays`的明确polygon
技术合成。只有小mask采样生成像素，其余原像素保持；原眼框、睫毛、虹膜、眉和嘴分层恢复。
不要整脸替换、强制对称或把原眼画在移动眼睛下面。

当前本机常服案例中性2347×1253 RGBA与原图全等、补丁外差0；独立虹膜只影响IrisLeft/Right，
位于原生clip mask内。14 drawable、19实际参数、12表情、Core133组合及实际离屏渲染通过。
公开只有[数值报告](../examples/phoenix/verification-summary.json)、坐标和提示词，官图/派生PNG/MOC3不附带。
该案例已在本机原生AIRI桌面可见；位置调整、12表情与完整语音联合验收仍待完成，不能当作最终成品。

必要陷阱：Core与目标shader各有V转换，额外再翻一次会采到倒置局部纹理。
构建器现用PNG top-down UV，Core验证检查实际UV原点，渲染器再检查真正贴图画面。
没有画侧脸/隐藏肢体时保持浅头动，不把二维仿射叫作3D转面或手臂动画。

## 本地有表现风格的中文 TTS

适用于：已有可用GPU PyTorch/Torchaudio环境，可为1.7B TTS准备约4.52GB本地文件。
先清点已有ASR/TTS服务和权重，复用匹配文件；不要重复下载或改坏其他程序的环境。
完整安装、哈希验证、API和试听入口在[voice/README.md](../voice/README.md)。

```text
python voice/install_dependencies.py --target /path/to/isolated-voice-deps
python voice/download_models.py --models-root /path/to/shared-models/TTS
python voice/server.py --deps /path/to/isolated-voice-deps --model-dir /path/to/shared-models/TTS/Qwen3-TTS-12Hz-1.7B-CustomVoice
```

默认API `http://127.0.0.1:9945/v1/`，model `phoenix-qwen3-tts-local`，voice `phoenix-soft`。
内置Serena配合三种原创风格描述，无声优录音或克隆。实际3段WAV、MP3、模型/音色列表、
输入拒绝、8请求队列/第9拒绝、断开清理及后续并发句块都测试通过；运行请求层外网尝试0。
见[已保存报告](../voice/tests/verification.json)与[样例/延迟](../voice/samples/sample-report.json)。

限制：首次返回等整句batch生成，示例4.48–5.20秒音频耗时6.67–15.88秒；不承诺97ms流式。
这只是TTS，ASR与屏幕/麦克风权限单独配置。模型、GPU/平台依赖与AIRI不在工具ZIP中。
本次打包保留已有真实报告，没有重复占用GPU合成。

## Windows 四模块配置台模板

适用于：已有兼容offline-settings/revision契约的AIRI wrapper与本机服务，需要明确选择聊天、
视觉、ASR和TTS。代码和依赖条件见[控制台说明](../control-center/README.md)。发布副本把工作台、
模型、Python、部署根和私有状态目录改为环境参数，不含那台机器的settings和profile。
历史实用版25API、18交互UI、7最终只读UI通过；发布副本另有7项真实隔离HTTP/偏好不改设置/
apply保留角色与其他设置/精确备份/CSRF/固定命令拒绝测试，见[副本报告](../control-center/tests/template-verification.json)。

这是有验证证据的配置方法和模板，不是已经安装所有后端的通用AIRI安装器。完整wrapper首版尚待
独立快照/验收收录，未具备说明中的服务和启动器时，不把按钮操作视为部署成功。

## 原创人设与可导出的 AIRI 卡

适用于：已有来源依据与原创角色扮演文案，目标为AIRI/CCv3/V2。

```text
python character-tools/export_cards.py examples/phoenix/character.json --out work/card-only
```

实际用已安装AIRI schema/ACT normalizer/表达式上下文验证了卡结构、12精确名称及reset，
也验证了merge对现有卡的保留与幂等。见[报告](verification/character-cards.json)。
给导出器加`--model /path/to/already-validated-model`才会把模型打进角色包；
card-only有意不含动画模型。来源见[设定与表情索引](../examples/phoenix/sources.json)。

实际面部控制走`<|ACT {"expression":{"name":"E11_ClosedEyeSmile","duration":3}}|>`，
不是随意写一个情绪词。model3必须提供同名exp3。TTS provider/model/voice可被活动卡覆盖，
应一起核对；卡不会安装9B、ASR或授予麦克风/屏幕权限。此处的schema/ACT测试不等于
最新候选已完成真实AIRI import、可见表情、播放和lip sync验收。

## 给自己的 AI agent 使用

完整ZIP的根入口是`SKILL.md`，Skill名`airi-character-forge`；普通agent可直接读文件并调用CLI。
MCP是可选legacy2025-11-25 stdio接口，18协议/路径边界测试及真实robot调用通过，
不宣称支持任何未来协议。见[API说明](agent-api.md)与[脱敏测试汇总](verification/release-checks.json)。
其他agent使用自己的语义图像工具；本程序没有隐含的Codex或付费图像账户。

## 单独列出的未完成项

- 官图2D原生桌面已可见，继续调整位置并联合验证12表情、看鼠标、语音和lip sync。
- 三张独立卡：官图2D、待制作站姿2D、用户自有3D；3D本机前台显示已验证，卡/来源与附带readme分别记录，模型不公开。
- 两套时装Live2D制作。
- 聊天贴纸/表情包的官方资源获取、AIRI配置及实际聊天显示；它不同于model3面部表情。
- 最新启动器对共享Electron路径的进程区分修复与完整重启验收，待实测证据后再列为可用方法。
- 最终组合配置的离线启动/停止/更新保留用户自定义数据检查。
- 现有任务全部完成后，最后再测说话→ASR→LLM→TTS延迟并发布经过验证的测量方法/有效方案；当前未进行这一项优化。

链接配布的条款仅适用于对应来源；用户另行提供的本机3D文件按其自己的readme/来源记录，不能仅凭其他配布页面替它下用途结论。官方或用户自有模型文件都不进入公开ZIP。
项目持续记录的是已验证方法、适用条件和必要陷阱，不发布聊天流水；见[记录约定](airi-change-recording.md)。
