# 复用模型的离线中文 ASR 与轻量 TTS

这是本机已验证的 9942 共享服务源码：SenseVoice int8 识别 + Melo 中文/英文普通女声（`zh_default`）。其他兼容 OpenAI 音频接口的应用可以复用同一进程，不需要各复制一份 ASR 模型。该音色没有角色声优克隆；有表现风格需求可选独立 [Qwen 服务](../voice/README.md)。

复制到自己的 `<base>/runtime/airi-speech`。将 `config.example.json` 改为私有 `config.json`，显式提供既有 Python、SenseVoice 目录与 FFmpeg。SenseVoice 目录应包含 `model.int8.onnx`、`tokens.txt`；不要把环境中的绝对路径提交到 Git。当前源码使用 `models/melo-zh-en` 下的本地 ONNX/字典/rule_fst，手动执行 `install-models.py` 获取固定修订，逐文件校验 HF LFS SHA256 或 Git blob SHA1。约 74.3 MB，权重不附包。

`requirements-native.txt` 是受测补充依赖版本。在兼容的 Python 中把缺少依赖装到该服务的 `native-packages`，ARM64 服务会在自己的 sys.path 加载它，保留已有 NumPy/SciPy/Pydantic 等环境包。不要照抄另一台机器的 Torch/CUDA 或覆盖共享环境。本机使用原生 ARM64 Python，未重装共享环境；其他架构/版本需自行验证 wheel。

```text
python speech-server.py
GET http://127.0.0.1:9942/health
POST http://127.0.0.1:9942/v1/audio/transcriptions  # multipart file/model/language
POST http://127.0.0.1:9942/v1/audio/speech          # JSON input/model/voice
```

ASR 模型 `sensevoice-local`；TTS 模型 `melo-tts-zh-en`；声音 `zh_default`；AIRI baseUrl `http://127.0.0.1:9942/v1/`。本地服务无付费账户，客户端要求 key 时可用 `local-offline` 占位。支持 WebM/WAV/MP3 输入与 WAV/MP3/PCM/Opus/AAC/FLAC 输出，FFmpeg 仅允许本地输入协议。启动器见 [launchers](../launchers/airi-speech-start.ps1)，停止只处理经 PID/解释器/脚本校验的进程；停止共享服务会影响其他调用者。

进程只监听回环，安装 DNS/socket 非回环阻断并自测，启动和运行不下载模型。不改系统防火墙。Silero 路由 GET/HEAD `/offline-assets/silero-vad/onnx/model.onnx` 读取部署目录的独立 2.24 MB VAD 文件，需使用 Transformers 对应的版本；不拿另一种 Silero ONNX 直接冒充。AIRI wrapper 还从已安装 Transformers 复制相匹配的 ORT JS/WASM。

[已完成验证摘要](verification-summary.json)包括中文 WAV/WebM 识别、合法 WAV/MP3、TTS→ASR 回转及外部请求阻断。这不证明麦克风设备或扬声器物理回放；`verify-offline.py` 会在自己的目录生成测试音频和报告，默认仍使用固定合成文本/配套模型测试音频，产物留私有。最新同句阶段计时见[探针结果](../diagnostics/README.md)，不把不同声线音频长度差异解释为纯引擎加速。

模型原始来源和逐文件哈希见 [model-source-manifest.json](model-source-manifest.json)；服务适配代码遵循根 MIT，第三方依赖/模型遵循自己的许可。

`verify-offline.py`的ASR回归额外要求原SenseVoice配布的 `test_wavs/zh.wav`（包含“时间”的固定中文句）；它不随本包复制。缺少该测试fixture不代表服务不可用，可用自己的固定合成WAV通过[HTTP探针](../diagnostics/README.md)另测；不能把未执行的fixture回归写成PASS。
