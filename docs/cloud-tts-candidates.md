# 云端 TTS 混合候选：接口核实与分层实测

核对日期：2026-10-25。控制台保留本地方案，只有使用者明确应用才切换在线语音。可以保留本地 SenseVoice 和 9B，只把选定的合成文本发给云端 TTS；这会失去该部分的完全离线能力。阿里云3.1在0.2.3修复后已有一次固定原创短句的真实API连通：首音频1.792s、完整3.28s WAV等待2.375s；见[匿名结果](../voice/aliyun-tts/verification-cloud-live.json)。n=1，不是横向基准，也未验证原生AIRI播放。Azure与OpenAI仍为 **UNMEASURED**。官方宣称的延迟不能代替当前网络、中文音色和 AIRI 播放路径的测量。

| 候选 | 当前接口与表现控制 | 按量计费方式与接入条件 |
|---|---|---|
| 阿里百炼实时 TTS | 当前官方实时指南推荐 **Qwen-Audio-TTS**，示例型号为 `qwen-audio-3.1-tts-flash`；WebSocket 分段文本输入与音频逐段返回。3.1/3.0 Flash/Plus 的系统、设计或复刻音色支持 `instruction` 自然语言语速/情感控制。旧 Qwen3 Instruct 参数表不能当作新版型号契约。 | 按实际型号、地区和当前价格表核对；不把旧 Flash 的价格套给 3.1。需要同地域 API Key、业务空间、模型权限及流式 adapter。云系统音色不等于本地 Serena，必须试听。见[当前实时指南](https://help.aliyun.com/zh/model-studio/realtime-tts-user-guide)、[API Key](https://help.aliyun.com/zh/model-studio/get-api-key/)、[官方价格表](https://help.aliyun.com/en/model-studio/model-pricing)。 |
| Azure Speech | 区域 REST `https://<region>.tts.speech.microsoft.com/cognitiveservices/v1` 接收 SSML，也可用 Speech SDK。`mstts:express-as` 控制 style/degree/role，prosody 控制语速/音高；支持范围必须按具体中文 voice/地区查询。 | 按处理字符收费，神经/HD、地区及层级不同；字符规则包含标点等，中文字符按官方计量说明折算。价格页在此次抓取显示动态占位，未抄成固定美元数。需 Speech 资源、region 与合法凭据；不是只更换 OpenAI baseUrl。见[REST](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/rest-text-to-speech)、[SSML](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-synthesis-markup-voice)、[计量说明](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/text-to-speech)、[价格](https://azure.microsoft.com/en-us/pricing/details/speech/)。 |
| OpenAI | 现有 `/v1/audio/speech` 的 `gpt-4o-mini-tts` 支持语音表现 instructions。但官方已宣布该模型及 tts-1/tts-1-hd 于 **2027-01-06 停用**，迁移目标是 Realtime `gpt-realtime-2.1-mini`，需要改 API 工作流，不能直接把它填入 Speech API 的 model 字段。 | 原 mini TTS 按输入文本/输出音频 token 计费；新 Realtime mini 也按文本、音频 token 分项计量，不能把音频 token 价格当作每分钟价格。需 API 凭据、Realtime adapter 和中文试听/时延测试。见[当前 TTS 指南及停用提示](https://developers.openai.com/api/docs/guides/text-to-speech)、[旧 mini TTS 计费](https://developers.openai.com/api/docs/models/gpt-4o-mini-tts)、[新 Realtime mini 计费](https://developers.openai.com/api/docs/models/gpt-realtime-2.1-mini)。 |

当前 AIRI 的完整句音频等待与客户端播放路径仍须适配；只改服务地址不会自动变成边收边播。后续试验只用固定原创测试句，不发送私人聊天、麦克风录音或屏幕内容。为每项分别记录网络/接口首音频、可解码音频、音频长度、连续生成 RTF、听感及 AIRI adapter 是否实际接通；云端接口首包也不等于声卡已播放。没有凭据时保留未测，不依据估计选成默认。

当前 SDK 与模型页面存在个别范例/通用端点列表不一致；以专门 API 指南的明确限制为准，并在接入前重新核对模型权限、地区、计费与接口契约。
