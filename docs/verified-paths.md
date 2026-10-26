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
历史实用版25API、18交互UI、7最终只读UI通过；发布副本另有8项真实隔离HTTP/偏好不改设置/
apply保留角色与其他设置/精确备份/CSRF/固定命令拒绝测试，见[副本报告](../control-center/tests/template-verification.json)。

这是有验证证据的配置方法和模板，不是已经安装所有后端的通用AIRI安装器。完整wrapper与路径可配启动器见[快照说明](../airi-integration/offline-shell/SETUP.md)；需先满足既有构建、依赖与模型条件，不把按钮操作当作新机器部署成功。

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

## 实际3D接卡与API声链

[可复用方法和源码](../airi-integration/README.md)记录受测AIRI的真实Pinia流程：
私有`pmx-zip`→addDisplayModel→addCard绑定真实model.id→activateCard；实际桌面完整3D显示通过。
模型和纹理不发布，按用户自有文件自己的readme/来源记录。原创自然手臂/待机已通过原生VMD解析、实际MMDScene渲染、主app导入和前台可见检查；物理保持关闭。

同一文档附独立synthetic binding验证器：实际SDK合成文本完成已观察，TTS全局计数变化未精确关联（因果INCONCLUSIVE），
message/complete各1、预期短语出现、TTS增加1，renderer/屏幕/服务错误0。
38970ms仅是旧SDK文本与同期全局TTS计数观察的总耗时，语音因果关联未证实；它不是TTFT、TTFA或端到端播放延迟。
用户安排在既有任务完成后才排查端到端延迟，当前不提前优化。

## 聊天贴纸：制备与导入helper

[sticker-tools](../sticker-tools/README.md)查询官方米游社公开catalog，制备显式本地图像配方，
并通过真实Pinia stickers store API导入。官方catalog本次未匹配到菲欧妮完整包，不能声称全网不存在。
本机已从原有官方公开视频故事板缓存做9个静态帧crop，哈希/重复一致和尺寸检查通过；图片不公开。
Pillow5项真实PNG测试与Node5项synthetic store测试通过。真实主app store已导入9个、enabled=true、frequency=50；设置库实际缩略图渲染已通过，真实聊天选图/显示仍待验收，
不混进已完成端到端方案。它是设备全局贴纸库/频率配置，不是每卡Live2D面部表情。

## 给自己的 AI agent 使用

完整ZIP的根入口是`SKILL.md`，Skill名`airi-character-forge`；普通agent可直接读文件并调用CLI。
MCP是可选legacy2025-11-25 stdio接口，18协议/路径边界测试及真实robot调用通过，
不宣称支持任何未来协议。见[API说明](agent-api.md)与[脱敏测试汇总](verification/release-checks.json)。
其他agent使用自己的语义图像工具；本程序没有隐含的Codex或付费图像账户。

## 单独列出的未完成项

- 官图2D原生桌面已可见，继续调整位置并联合验证12表情、看鼠标、语音和lip sync。
- 三张独立卡：官图2D、站姿2D、用户自有3D；站姿Core135组合/WebGL29帧并导入独立卡已通过，三卡完整UI/音频联合验收另做。
- 两套时装由用户暂缓，当前范围不包含；仅保留来源参考。
- 聊天模型实际选贴纸并在回复中显示的验收；主app导入/持久化/设置/缩略图已通过，它不同于model3面部表情。
- 新AIRI版本更新后重新核对内部API与用户自定义数据保留；当前版本完整启停已通过。
- 固定合成输入的HTTP阶段计时已执行，见[探针](../diagnostics/README.md)。真实VAD/host关联/声卡物理播放与候选选型仍分层验收；当前默认保留。

链接配布的条款仅适用于对应来源；用户另行提供的本机3D文件按其自己的readme/来源记录，不能仅凭其他配布页面替它下用途结论。官方或用户自有模型文件都不进入公开ZIP。
项目持续记录的是已验证方法、适用条件和必要陷阱，不发布聊天流水；见[记录约定](airi-change-recording.md)。

## 原生MMD自然待机方法

[mmd-tools](../mmd-tools/README.md)从实际骨骼方向生成原创12秒VMD，经原生`useMMD().addMotion(File)`和`idleMotionName`播放，不替换AIRI渲染循环。受测VMD370关键帧/10骨骼/0morph，首尾相等且四元数单位化，5项helper检查通过；实际MMDScene独立预览已显示完整贴图与手臂约13度自然下垂。主app store导入ready，当前原生前台已看到自然待机；完整音频/口型联合仍分层验收。

只附原创骨骼动作，不附用户PMX、纹理或视频。不同骨架/裙摆/饰品必须各自检查；当前模型物理关闭，因为此组合会拉伸头发，不能声称物理已修好。待机不写头/眼/嘴/morph轨道以保留原生控制路径，但没有据此冒称真实TTS口型全部验过。

### 视觉语义不能被像素QA代替

早期站姿候选通过Core组合和实际WebGL后，仍未满足使用者的脸部自然度要求。长睫毛bbox确实会误导虹膜定位，但006把瞳孔强压到眼白区域质心仍不是人物相似度答案。007恢复使用者选定参考的眼型、小瞳、高光、眉嘴和自然会聚，再按脸部鼻/嘴/头面基准定位；135 Core组合、29标准＋45扩展实际WebGL帧和33项检查通过。独立眨眼无金色残影、四向gaze和半闭眼语义方向已测，身体/脸基准复合运动也单独验证；这不等于使用者已最终接受，也不冒充主app全功能联合验收。详见[参考脸QA方法与边界](live2d-face-qa-lessons.md)和[匿名报告](../diagnostics/live2d-face-qa-status.json)。

## Windows一键重启与UTF-8 JSON的已验证修复

本机实际全停/全启后9941、9942、9945与桌面ready，一键start exit0；独立9931工作台原PID保持。站姿模型换新版仍保留cardID，贴纸复用9无重复，原创MMD idle复用同名哈希条目。见[脱敏汇总](../airi-integration/verification/one-click-restart-summary.json)。[wrapper/launcher快照](../airi-integration/offline-shell/SETUP.md)单独收录；这份摘要不等于任意机器安装成功。

必要陷阱：PowerShell5的Get-Content默认会把BOMlessUTF-8中文当ANSI，导致ConvertFrom-Json失败。读取JSON应显式`-Encoding UTF8`；Python CLI经旧native stdout codepage传给PS时输出JSON unicode escapes（ensure_ascii=True），HTTP仍保持UTF-8。配置解析失败只输出固定错误，不把整份带provider字段的JSON打印进日志。发布的控制台选择/停止模板已同步这一修正，私有settings和备份不公开。

### 声链验证的因果边界更正

历史38970ms工具使用overrides.binding，所测compiled scene路径speaks=false。SDK message/complete是生成完成事件而非首token；全局tts_requests在并发运行时无法关联到该请求。故该条只保留SDK合成文本完成与同期计数观察，声链因果INCONCLUSIVE。直接HTTP TTS返回WAV仍是有效独立证据。后续严格端到端测试必须关联正确host会话的合成输入、LLM输出、对应TTS请求与播放，不依靠同时增加的全局计数。

## 已测速度候选与默认保留

[实测选择表](speech-options.md)列Qwen默认与可选省输出别名、Melo和Windows慧慧；[控制台](../control-center/README.md)已经显示两个新选项的实际接口证据并恢复原Serena默认，未自动应用或播放。Qwen可选模式在本句HTTP对照减少约19.8%等待且WAV一致；SAPI三次完整WAV0.147/0.055/0.029s但音色功能不同。系统声线不等于角色风格。阿里云3.1另有一次固定句API连通，Azure/OpenAI仍未测；不同内容/时段的单次结果不构成横向排名。

## 文字首字、权限开关与Windows登录

[9B文字响应审计](../diagnostics/llm-latency-audit.md)核实确切llama.cpp版本的思考开关，并用39和11992 token合成输入分别测首字与server prefill；每种一次，不能宣称实际角色平均值或已实现prompt压缩提速。单slot屏幕争用也是机会证据，未把某个用户等待归因给它。

[统一屏幕关闭方法](screen-access-off.md)收录已测试的取消、epoch和writer清理，以及按钮/工具权限联动；真实原生按钮开关后79.07秒无新发布，两窗口均关闭且旧writer已清，详见单独匿名native报告。[Windows登录自启](windows-sign-in.md)只注册已有一键启动器，读取回验证，不冒称已经注销/登录验过。

[MMD构图保存](../airi-integration/offline-shell/MMD-CAMERA-PERSISTENCE.md)保存摄像机而非仅模型平移/scale：按modelId和主窗/preview分开，模型fit完成后恢复，初始化和旧异步加载不能覆盖新数据。V2的41项检查包含实际bundled OrbitControls数值投影往返与Vue受控model时序；主app重启已读回stage/restored并核对近景。补丁先确认唯一compiled region和全部锚点，未知版本失败停止；V1升级必须用冻结生成器重放原备份并逐字节匹配，上游源码保持干净。

## 本机保存密钥的可选云端语音

[阿里云转接服务](../voice/aliyun-tts/README.md)提供9949完整WAV接口，控制台可见配置/固定句试听/明确应用流程，当前本地选择不变。简易版与高级3.1分别采用对应官方端点和音色；密钥用当前用户DPAPI保存，AIRI只存独立本地token。25项adapter、14项console隔离检查与真实Windows启动/重复启动/健康/停止通过；它们验证可复用程序路径，真实云请求为0。

取得自己的Key后才做云端合成测试；首上游音频、完整WAV、实际AIRI播放分开计量。当前AIRI仍按完整小句播放，不能从上游SSE推断低延迟开口。详见[具体边界与官方来源](../voice/aliyun-tts/verified-method.md)。

### 云端实际连通与格式检查

0.2.3在[47项合成Key/DPAPI](../voice/aliyun-tts/key-validation.md)与[43项合成SSE/WAV](../voice/aliyun-tts/streaming-wav.md)回归后，另通过一次真实3.1固定句API连通：首音频1.792s、完整3.28s WAV2.375s。Key点号兼容与严格已完成流的占位头归一化可复用；不要把未知/有限截断WAV一律放行。该n=1结果不等于实际AIRI播放、物理总延迟或跨候选性能排名，私人Key/Host/音频均不公开。

[实际应用/启动](../voice/aliyun-tts/verification-airi-startup-live.json)另确认全局与三卡speech、保留本地聊天识别和原生听状态；代理短句HTTP200。启动就绪、有效WAV和实际播放是不同验收：尚未测用户实聊/声卡总延迟与长期稳定性，出现过一次待定位的窗口退出。
