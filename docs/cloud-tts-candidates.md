# 云端 TTS 混合候选：文档核实，尚未本机实测

核对日期：2026-10-25。当前默认仍是本地 Qwen。可以保留本地 SenseVoice 和 9B，只把选定的合成文本发给云端 TTS；这会失去该部分的完全离线能力。以下三项都没有在本机提供凭据或执行合成，状态均为 **UNMEASURED**。官方宣称的延迟不能代替当前网络、中文音色和 AIRI 播放路径的测量。

| 候选 | 当前接口与表现控制 | 按量计费方式与接入条件 |
|---|---|---|
| 阿里百炼 Qwen TTS | Flash HTTP 使用 `/api/v1/services/aigc/multimodal-generation/generation`，支持 SSE；Realtime 使用 DashScope WebSocket 文本分块/音频 delta。SDK 参数表把自由 `instructions` 限于 **Qwen3-TTS-Instruct-Flash-Realtime**，不能假设普通 Flash 同样支持。 | 按输入字符计费，具体型号/地区价格不同；示例普通 Flash 北京为 ¥0.8/万字符，不能将该价格套给 Instruct。需要匹配北京或新加坡地区的 key、模型权限及 adapter。见[HTTP API](https://help.aliyun.com/zh/model-studio/qwen-tts-api)、[Realtime SDK 参数表](https://www.alibabacloud.com/help/en/model-studio/qwen-tts-realtime-python-sdk)、[官方价格表](https://help.aliyun.com/en/model-studio/model-pricing)。 |
| Azure Speech | 区域 REST `https://<region>.tts.speech.microsoft.com/cognitiveservices/v1` 接收 SSML，也可用 Speech SDK。`mstts:express-as` 控制 style/degree/role，prosody 控制语速/音高；支持范围必须按具体中文 voice/地区查询。 | 按处理字符收费，神经/HD、地区及层级不同；字符规则包含标点等，中文字符按官方计量说明折算。价格页在此次抓取显示动态占位，未抄成固定美元数。需 Speech 资源、region 与合法凭据；不是只更换 OpenAI baseUrl。见[REST](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/rest-text-to-speech)、[SSML](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-synthesis-markup-voice)、[计量说明](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/text-to-speech)、[价格](https://azure.microsoft.com/en-us/pricing/details/speech/)。 |
| OpenAI | 现有 `/v1/audio/speech` 的 `gpt-4o-mini-tts` 支持语音表现 instructions。但官方已宣布该模型及 tts-1/tts-1-hd 于 **2027-01-06 停用**，迁移目标是 Realtime `gpt-realtime-2.1-mini`，需要改 API 工作流，不能直接把它填入 Speech API 的 model 字段。 | 原 mini TTS 按输入文本/输出音频 token 计费；新 Realtime mini 也按文本、音频 token 分项计量，不能把音频 token 价格当作每分钟价格。需 API 凭据、Realtime adapter 和中文试听/时延测试。见[当前 TTS 指南及停用提示](https://developers.openai.com/api/docs/guides/text-to-speech)、[旧 mini TTS 计费](https://developers.openai.com/api/docs/models/gpt-4o-mini-tts)、[新 Realtime mini 计费](https://developers.openai.com/api/docs/models/gpt-realtime-2.1-mini)。 |

后续试验只用固定原创测试句，不发送私人聊天、麦克风录音或屏幕内容。为每项分别记录网络/接口首音频、可解码音频、音频长度、连续生成 RTF、听感及 AIRI adapter 是否实际接通；云端接口首包也不等于声卡已播放。没有凭据时保留未测，不依据估计选成默认。

当前 SDK 与模型页面存在个别范例/通用端点列表不一致；以专门 API 指南的明确限制为准，并在接入前重新核对模型权限、地区、计费与接口契约。
