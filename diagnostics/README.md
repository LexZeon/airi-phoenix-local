# 分阶段延迟探针与实测边界

其他现有任务验收后已运行固定合成输入的隔离HTTP阶段测量。当前默认配置保留；候选先测后选，不能把这份HTTP探针当作真实麦克风/声卡全链结果。

`probe_latency.py`仅使用标准库，所有端点需显式指定为HTTP回环地址，禁止外部地址、代理和重定向。
默认ASR输入是随包原创Serena短合成WAV并检查固定哈希；也可用`--synthetic-audio`显式选择自己
生成的WAV。LLM/TTS只用固定原创合成测试文本。它不访问麦克风、屏幕、AIRI聊天或用户录音，
不保存转录、LLM回复或新生成音频；默认只向stdout输出汇总JSON，`--out`可写同样的汇总。

重复同样的阶段测试，例如：

```text
python diagnostics/probe_latency.py --asr-url http://127.0.0.1:9942/v1/audio/transcriptions --asr-model sensevoice-local --llm-url http://127.0.0.1:9941/v1/chat/completions --llm-model airi-qwen3.5-9b --tts-url http://127.0.0.1:9945/v1/audio/speech --tts-model phoenix-qwen3-tts-local --tts-voice phoenix-soft --out /path/to/private-summary.json
```

可用`--mode asr|llm|tts`只测某段；默认all依次独立请求。`--repeat 1..5`默认1，不自动warmup；
`--timeout`默认120秒，`--max-tokens`默认128。`--api-key-env VARIABLE`可读取现有进程环境中的
本机服务密钥，不把密钥或环境变量内容写入结果。脚本不安装、下载或启动任何模型服务。

`--tts-sequence 2..5`可顺序生成多句固定合成文本，记录总RTF、排除首句后的生成RTF，并以
真实完整WAV返回时刻计算虚拟连续播放缺口。此处没有实际播放设备；虚拟缺口不是实测声卡卡顿。
默认只有1句，不自动扩大请求量。配置始终保留，不自动切换到任何候选方案。

## 计时的定义

| 阶段 | 输出 | 未覆盖 |
| --- | --- | --- |
| ASR | 合成WAV请求的响应headers、首body字节、完整响应总耗时、转录字数、输入实际采样帧秒数 | 真实麦克风/VAD/endpointing等待、采集设备延迟 |
| LLM | 第一个SSE事件、首个非空content或reasoning delta、首个可见文本、完整流总耗时、字数/usage | AIRI真实角色/工具上下文、排队归因、tokenizer层面的硬件首token时钟 |
| TTS | HTTP首body字节、首个完整可解码WAV可用时间、完整返回耗时、合法WAV帧秒数与RTF；可选多句生成率/虚拟播放缺口 | 声卡/扬声器/声学回放；首字节并不代表流式合成首音，physical TTFA为null |

WAV时长根据`fmt`与`data`chunk、block alignment、sample rate计算，包含文件中的静音，
不冒充只含发声的VAD时长。LLM只把实际解析到的非空delta算作首token；role-only chunk不算。
如果后端无SSE、返回空转录/空回复/无效WAV，会留下失败码，不把HTTP200当成功。

这是**隔离的HTTP阶段探针**，LLM输出不再传给TTS，三段求和不是实际对话端到端延迟。
冷加载、模型排队、资源争用、推理模式和输入长度会影响数字。真实说话→停止判断→ASR→
当前AIRI角色LLM→TTS→物理播放需要另外的实机链路测量，不能用这个探针替代。

历史38970ms SDK文本与TTS全局计数观察的语音因果关联未证实，见
[airi-integration](../airi-integration/README.md)，不影响独立HTTP阶段测量的有效性。

线上或混合候选需要独立、明确的测试和凭据，且只能使用固定合成文本；这个工具不会放开
外网或使用私聊/画面。没有凭据或没执行的候选一律标UNMEASURED，不能把估计写成实测。
按用户最新要求，先测候选，再提供选择，默认保留当前方案。

## 独立只读 Live2D controls inspector（已执行）

这是另一个工具，不进行延迟测量。`inspect-live2d-controls.cjs`使用用户现有Electron和已编译AIRI的manifest inspector，在独立hidden renderer/profile读取指定本机ZIP，输出表达式名/参数数和哈希，无live Pinia/card/profile写入。

```text
/path/to/electron diagnostics/inspect-live2d-controls.cjs --renderer /path/to/airi/out/renderer --zip /path/to/private/model.zip --out /path/to/private/isolated-probe
```

当前AIRI编译版本实际读取12表达式成功，见[数值报告](compiled-controls-verification.json)。ZIP/纹理和隔离profile不附包。`activeLive2DModelControls`只表示当前active头像；未激活的Live2D卡或随后切为MMD时该getter为0并不说明模型不支持表情。

受测源码在leader内`activateCard`会await controls加载，但follower的同步快照可以在action reply后才应用；本机修正为激活后有界等待，实际主app getter最终12。inspector失败只`console.warn`，不能只凭errorCount0排除失败。仍须区分ZIP解析、active getter、实际ACT执行与可见画面四层证据。

## 实际阶段测量（2026-10-25，两次固定短输入）

| 阶段 | 第一次 / 第二次 | 边界 |
|---|---|---|
| SenseVoice | 2.619s / 0.233s | 5.2s固定合成WAV；含冷/暖差异，不含VAD或麦克风 |
| 小LLM请求 | TTFT 3.422s / 0.079s | prompt仅28tokens；不是实际AIRI角色与工具prompt |
| Qwen Serena默认风格 | 完整WAV 8.470s / 12.065s；音频5.2s，RTF1.629 / 2.320 | 首字节接近完整WAV；未听声卡首声 |
| Melo普通女声 | 完整WAV 2.997s / 3.000s；音频3.088s，RTF约0.971 | 相同输入文字，不同音色/时长；风格自然度需试听 |

原始脱敏汇总：[Qwen与ASR/LLM](reports/baseline-2rep.json)、[Melo](reports/melo-2rep.json)。两次是顺序请求且没有自动warmup，不足以估算延迟分布或保证吞吐；不同输出秒数不能仅比较绝对生成时间。这些独立阶段不能相加冒充一条真实AIRI对话。连续播放序列另测，没有执行的RTF/物理首声保持未测。

[源码审计](latency-source-audit.md)核实当前compiled gate与分句/队列边界；VAD1200ms/32ms窗口约1216ms仅是代码计算，非实测endpointing。严格host nonce/turn/segment关联方案目前是设计，未宣称已实现。

[三项云TTS文档候选](../docs/cloud-tts-candidates.md)全部UNMEASURED，不把文档或宣传数字混入本机结果。
