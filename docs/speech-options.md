# 保留默认，先按实测选择语音方案

本轮使用固定原创合成句，未访问私聊、麦克风或屏幕内容，未切换用户的默认卡或声音。当前默认仍是 `phoenix-soft`。以下是不同验证层级，不能把文件生成、HTTP 返回和扬声器首声混在一起。

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

[Windows SAPI adapter源码与实际验证](../voice/windows-sapi/README.md)独立监听9947，随机本机Bearer token不进入公开包/偏好响应，默认未切换。上述HTTP数字包含整份合法WAV收到的客户端wall time；不是只引用COM内部生成时间，也不代表扬声器已经发声。
