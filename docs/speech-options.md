# 保留默认，先按实测选择语音方案

比较测试使用固定原创合成句，未访问私聊、麦克风或屏幕内容，也未在测试中切换用户的卡或声音。工具的初始默认是 `phoenix-soft`；使用者可以明确选择优化版。以下是不同验证层级，不能把文件生成、HTTP 返回和扬声器首声混在一起。

| 本地方案 | 当前实测 | 保留/改变的能力 |
|---|---|---|
| Qwen Serena 默认 | 9945实际HTTP ABBA，n=2，中位完整5.2s WAV等待7.580s | 保留既有音色/表现风格；整句批处理；尚未测声卡首声 |
| `phoenix-soft-efficient` 可选别名 | 同组n=2，中位6.082s，约少19.8%；四个WAV逐字节相同 | 仅本请求在GPU锁内不返回未用的残差predictor hidden states，finally还原；Serena、指令、seed不变，默认不切。仅固定句证明等价；背景负载下收益不恒定 |
| Melo 普通女声 | 独立HTTP两次2.997/3.000s，声音3.088s，RTF约0.971 | 完全离线且轻量；声线/韵律与Serena不同，没有Qwen自然语言表现指令 |
| Windows 慧慧 SAPI | 9947真实HTTP三次完整WAV0.147/0.055/0.029s，声音5.4145s；另测文件合成0.0988/0.0110s | 完全离线、无需新增权重；系统声线与角色表现明显不同。36项API/安全/队列/生命周期通过，AIRI实际host播放与物理首声另验 |

同组Qwen四次请求为默认→可选→可选→默认，header确认模式，所有WAV同一SHA256。另有31次真实GPU候选生成，覆盖文本输入模式、残差贪心采样、hidden-state开关与组合；前两者和组合没有改善本组完整WAV时间且改变音频，因此未启用。完整结果与复现命令在[voice/performance.md](../voice/performance.md)。这些是小样本同句/同环境结果，不是跨机器速度保证。

将同句分为两段的API模拟第一段2.781–2.938s可用，但第二段生成比第一段播放更久，计算缺口1.608–1.641s，韵律与合并音频时长也改变。没有播放声音，不能称无缝流式。AIRI已有分句机制，不能把这个模拟当成刚部署的新加速功能。

SenseVoice暖请求0.233s，小LLM的28token测试prompt暖TTFT0.079s；它们说明测试内容下的局部阶段，不代表真实AIRI角色/工具上下文。VAD、文本外层安全分句、TTS排队、解码与播放分别可能增加等待。源码中的1200ms VAD静音阈值只作机制解释，未测真人endpointing。见[阶段探针](../diagnostics/README.md)与[源码审计](../diagnostics/latency-source-audit.md)。

云端可只接TTS而保留本地识别与LLM，但本机没有提供相关key，三项均 **UNMEASURED**；接口、风格能力、计量与OpenAI迁移限制见[云端候选](cloud-tts-candidates.md)。不根据广告数字替用户选默认，也不把未接通的服务标成可用。

更换方案时只改所选的speech provider/model/voice，保留hearing、vision与角色；多张受管理卡可能各有modulesOverride，须同步所选卡而不是仅修改全局defaults。先保留原选择与revision，失败可回切。自动化结论只写实际覆盖范围：原SDK scene binding测试仅有文本完成观察，语音因果仍INCONCLUSIVE，不拿全局TTS计数作端到端证明。

## 在控制台启用 Serena 优化版与回退

适用：已有本仓库控制台、支持优化别名的9945服务，以及对应的一键启动器；先确认原声音能够正常使用。不需要另下模型或更换角色素材。

1. 打开本机控制台 `http://127.0.0.1:9944/`，在“角色声音”选择“Serena · 温柔优化版”。控制台选择ID是 `qwen-efficient`，实际模型仍为 `phoenix-qwen3-tts-local`，voice为 `phoenix-soft-efficient`。
2. 保留其他三项选择，点击“应用并启动 AIRI”；应用已运行时按钮显示“应用并重启 AIRI”。“记住选择”只保存偏好；“只应用设置”不会重启当前进程，不能单凭点击它就判断新voice已经载入。
3. 等待AIRI与声音服务就绪。受管理多卡应同时更新speech的provider/model/voice与selectionRevision，保留各自avatar和激活选择；不要只核对全局defaults而遗漏每卡override。
4. 回退时选择“Serena · 温柔”（`qwen-soft` → `phoenix-soft`），再执行同一应用/启动操作。这会恢复原请求模式，不需要回滚代码或下载权重。

约6.1秒来自前述固定5.2秒合成音频的HTTP小样本对照，不是每句话的承诺，也不是麦克风到扬声器的总等待。

[Windows SAPI adapter源码与实际验证](../voice/windows-sapi/README.md)独立监听9947，随机本机Bearer token不进入公开包/偏好响应，默认未切换。上述HTTP数字包含整份合法WAV收到的客户端wall time；不是只引用COM内部生成时间，也不代表扬声器已经发声。

已完成一次使用者明确选择后的实际启用：[匿名验证](../control-center/verification-efficient-activation.json)确认3张受管理卡的voice均为优化别名；主运行时与另一张2D卡解析结果匹配，3D卡模块更新/激活获确认，helper revision与配置对齐，声音/待机/贴纸ready、renderer错误0。控制台偏好也已同步。此证据验证配置与指定运行时读回，不是物理发声计时，不使用全局TTS计数证明因果；也不代表任何角色美术已经最终视觉接受。

回退步骤使用同一已测配置/启动机制；本次启用后没有再执行实际回退，以保留使用者选择。工具源码默认与既有ZIP不变，自己的部署按明确选择配置。

## 阿里云配置入口

控制台已提供[阿里云在线语音与固定句试听](../voice/aliyun-tts/README.md)。实现/隔离测试和owned服务启停已验证，真实云请求仍为0；没有云速度或实际人物开口的测量。先保留当前本地声音，自己在密码框保存Key、试听成功、再决定应用。首音频块与完整WAV分开显示，当前AIRI等待后者。
