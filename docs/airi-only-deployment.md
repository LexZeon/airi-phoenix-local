# AIRI 独立部署与共享语音资产迁移

适用条件：AIRI 已经能运行，但曾复用另一款桌宠目录中的 SenseVoice、FFmpeg 或 Python。要移除那款桌宠时，先把仍被 AIRI 使用的资产独立出来，再处理明确属于旧部署的目录。这里提供可复用方法，不提供自动删除脚本，也不预设另一台电脑的删除范围。

## 保留已用资产

1. 在私有部署配置中核对 `runtime/airi-speech/config.json` 的 `runtime_python`、`asr_directory` 和 `ffmpeg`；核对控制台与语音 adapter 的 Python 选择。不要只看快捷方式或文件夹名称判断依赖。
2. 复用现有 SenseVoice 文件，迁至 `<base>/runtime/airi-speech/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17`；复用 FFmpeg 至 `<base>/runtime/airi-ffmpeg`。保留识别所需的 `model.int8.onnx`、`tokens.txt`，以及复现实测需要的测试 WAV。无需重新下载同一权重。
3. 迁移前后按相对路径逐文件比较大小与 SHA256。全部一致后，更新私有 `config.json` 为新的实际绝对路径；保留其他识别/合成线程等原设置。Python 指向已经兼容的独立环境，避免让 AIRI 依赖待删除的 `.venv`。不要复制、覆盖无关共享环境。
4. 重启 AIRI 拥有的语音进程，让它重新载入配置。先检查 `/health` 与模型列表，再用固定测试 WAV 请求 `/v1/audio/transcriptions`，确认中文文本可用；实际麦克风与扬声器另验。
5. 通过用户已经授权的范围核对旧部署专属源码、虚拟环境、缓存和快捷方式，再执行清理。独立模型工作台、全局 Python、共享模型库及其他程序不能由名称相似就归入删除范围。若有其他调用者使用同一语音进程，先协调停机。

0.2.4 的清单在没有显式 `asr_directory` 时使用上述 AIRI 目录；设置 `AIRI_SPEECH_ROOT` 仍会改变对应服务根目录，显式私有配置仍优先。公开控制台启动器只使用 `AIRI_PYTHON`，不猜另一台机器的环境。阿里云 adapter 优先使用 `AIRI_ALIYUN_TTS_PYTHON`，其次兼容的已有创作 Python 或 PATH Python，不再查找另一款桌宠的 `.venv`。它会解析实际解释器并保留严格进程归属检查。

## 快捷方式与离线含义

建议桌面只保留启动、停止、更新 AIRI 与 AIRI 控制台四个入口，目标分别是已有 `launchers/airi-start.ps1`、`airi-stop.ps1`、`airi-update.ps1`、`control-center-start.ps1`。启动脚本所用环境参数应写在自己的私有启动配置中。更新源码需要网络；不要因目录名或快捷方式含“本地”就认为当前聊天与声音都离线。

本地聊天和本地 ASR 可以与云 TTS 同时使用。若当前声音选择阿里云，合成回复文字仍需联网；需要全离线时，使用者应明确切换并分别测试已经安装的本地声音。保留原角色卡、声音选择、3D 构图、屏幕观察和电脑控制关闭状态；迁移资产不授权自动切换模型或打开权限。

## 验证边界

本次已有部署中，SenseVoice 的 `model.int8.onnx` 与 `ffmpeg.exe` 两项关键文件迁移前后 SHA256 相同；整目录同卷移动后，用原配布中文 WAV 和经迁移 FFmpeg 转成的 WebM/Opus 分别完成识别，语音服务 `ready=true` 且本地外连限制启用。没有做整目录逐文件资产清单验收。控制台用独立既有 Python 启动并返回 HTTP 200。首次 WAV 请求约 5.252 秒、随后 WebM 请求约 0.733 秒；输入处理、冷热状态和调用次序不同，这两次不构成格式或引擎性能对照。没有做新云请求，也没有测物理麦克风或扬声器。

该已有部署的新版启动器另修复了 Windows PowerShell 5.1 `Restricted` 环境下的 WMI 固定子脚本启动：外层的临时 `Bypass` 不会自动传给独立子进程，必须在受控、固定的 PowerShell 子命令中显式传入流程级 `-ExecutionPolicy Bypass`，不更改全局策略。修改后真实启动退出 0，原 Job/归属守卫保留。公开包的语音启动模板没有该 WMI/broker 分支，其 AIRI 父启动器已经显式传入该参数；本次没有把新版生命周期实现移植进公开老模板，也没有据此声称两者实现或验收相同。

本次发布的实际迁移证据与离线回归见 [0.2.4 检查](verification/release-0.2.4-checks.json)。两项关键文件哈希相同与整目录同卷移动后的功能测试支持本次迁移可用，未宣称逐文件资产清单验收；固定 WAV 的 HTTP 识别不等于物理麦克风到扬声器已完成测试，也不证明云 TTS 变成离线。源码包不包含模型、FFmpeg 二进制、私有配置、删除清单或本机清理脚本。
