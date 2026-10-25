# 可审计的离线 AIRI wrapper 与启动器

这是已在 AIRI 0.12.0、Electron 43.4.1 x64、Windows ARM64 上运行的自编 wrapper 快照。原 AIRI main/renderer、独立授权的 Core 和外部模型不附包。它不是完整安装器，也不保证未来 AIRI 私有 store/API 不变。

在自己的部署根目录准备以下布局，先备份原有文件再选择性安装模板；不要覆盖真实配置或正在使用的 profile：

```text
<base>/airi/                       # 已按上游依赖版本编译的 AIRI
<base>/runtime/airi-offline/        # 本目录的 7 个运行源码与 package.json
<base>/runtime/airi-speech/         # shared-speech 源码、自己的 config.json 与本地依赖/模型
<base>/runtime/airi-qwen-tts/        # 可选既有 9945 服务及 start.ps1/stop.ps1
<base>/runtime/airi-offline-assets/silero-vad/onnx/model.onnx
<base>/launchers/                  # 本仓库对应 airi-*.ps1
<base>/logs/  <base>/backups/       # 私有；不提交 Git
```

复制 `offline-settings.example.json` 为部署目录的 `offline-settings.json`，核对现有本机 endpoint 和模型名，增加自己的 revision。示例没有私人数据，也未开启麦克风、自动发送、屏幕采样、角色导入或贴纸。没有提供虚构的模型路径来声称能自动导入角色；需要角色时配置自己实际拥有的 cardFile/modelZip，并使用真实应用 API 注册。

在使用启动器的同一环境中配置 `AIRI_COMPANIONS_ROOT`、可选 `AIRI_REPO_ROOT`，以及 `AIRI_GGUF_MODEL`（已存在的 Qwen3.5-9B-Q4_K_M）、`AIRI_MMPROJ`、`AIRI_LLAMA_SERVER`。模型启动模板保留受测尺寸与 32K context 检查，适用于该确切模型/投影组合；换模型必须重新核对参数/容量，不能仅更换文件名。可选 `AIRI_CUDA_BIN` 指定既有 CUDA bin；不安装 CUDA。

`airi-start.ps1` 依次检查 9941、9942、按选择启动 9945，再复制 wrapper 至 `airi/apps/stage-tamagotchi/out/offline-shell` 并启动现有 Electron。需要预先提供 9945 的启动脚本时，可参考 [voice](../../voice/README.md) 的服务命令，在自己的部署环境编写明确的 Python/deps/model 路径；此包不假造通用 GPU 安装脚本。`airi-stop.ps1 -KeepServices` 只退出桌面；不加开关会停止这些经身份校验的受管理服务。`airi-update.ps1` 手动备份、要求干净源码并 `pull --ff-only`、锁文件安装和构建，不强制 reset/clean。

PowerShell 5 模板使用 UTF-8 BOM，读取中文 JSON 显式 `-Encoding UTF8`。只修改子进程 PATH。初次安装/手动更新需要网络；正常启动重用本地运行时与模型。Node、AIRI/Electron、SenseVoice、Melo、Qwen、Silero、ORT 各有自己的许可和获取步骤，模型不在本 ZIP。

`GET http://127.0.0.1:9943/health` 暴露经过筛选的就绪/错误计数，没有密钥、画面、聊天或任意执行路由。wrapper 保留 selected-localStorage 备份；旧配置可能有 provider key，因此备份必须私有。网络策略仅作用本应用进程，默认阻断非回环请求，不能同时假定云 TTS 可用；混合候选需另行显式调整策略与 adapter 并实测。

当前本机实际全停/全启通过，9941/42/45 与桌面 ready，独立 9931 服务未变，贴纸/待机复用无重复。公开副本只将路径改为环境配置并做语法/隔离检查，未在另一台新机器重装验收。SDK 文本观察不是语音因果测量；详见[证据边界](../README.md)。

## 此快照的配置限制

当前 `initializeManagedCharacter` 以 primary `character.enabled` 为总入口：关闭主Live2D会同时跳过additionalCharacters、stickers和mmdIdle。本示例全部关闭，供保留原默认角色的基础语音接入。若要用附加MMD/站姿卡、受管理贴纸或待机，必须先提供真实可用的primary Live2D/card并启用；此快照不声称无需primary的纯MMD导入流程已支持。单独的3D bootstrap函数可由已授权的MAIN-world调用者使用，但那是另一条集成路径。

`APP_USER_DATA_PATH` 是直接启动wrapper时的override；随包一键启动器固定使用 `<AIRI_COMPANIONS_ROOT>/runtime/airi-data`，更新器也备份此目录。不要设置一个被启动器覆盖的自定义profile后误以为更新器已备份它。需要其他profile布局时应同时修改启动/停止/更新/控制台解析，并独立测试。
