# 完成的 SSE 与流式 WAV 占位长度

一次真实 `qwen-audio-3.1-tts-flash` 请求通过鉴权并返回音频后，本地严格WAV检查仍报“不完整”：该响应使用尚未回填的RIFF/data长度，而不是普通有限文件长度。不能因此把所有截断WAV都当作有效音频。

兼容修复只接受这一对已观察到的占位值：RIFF `0x7fffffbf`、data `0x7fffff9b`。还须满足44字节标准头、fmt长度16、PCM格式1、单声道24kHz/16bit、byte rate48000、block align2，以及非空偶数字节payload。嵌入另一个可识别WAV头的情况因边界不明而拒绝。

仅在上游SSE明确给出 `finish_reason=stop` 后才启用归一化，将两个长度改为已收到的实际字节数，再走原WAV验证/重封装。单独的`[DONE]`、断流、未知占位值、有限长度截断、奇数字节、其他音频格式与不一致片段仍失败。上游响应大小和时间上限保持不变。

`python verify_stream_wav.py`用自行构造的PCM与内存假SSE通过43项回归。真实网络连接被禁止，private配置读取也被禁止；它验证完整协议/已知头修复及拒绝边界，不是云端性能或声音质量测试。见[结果](verification-stream-wav.json)。

[真实固定短句连通](verification-cloud-live.json)另成功一次：上游首音频块1792.475ms、完整合法WAV2375.227ms、音频长3.28秒。n=1，仅适用于该请求/网络/模型，不是候选横向基准。当前AIRI等待完整小句ArrayBuffer再播放，仍不等于人物开口或麦克风到扬声器总耗时。
