# 可选阿里云语音连接

这是 AIRI 的本机 WAV 转接服务，监听 `127.0.0.1:9949`。云端合成要联网，识别、聊天与屏幕权限仍独立配置。无需下载新语音权重；本机程序使用 Python 标准库。

## 部署与使用

需要 Windows、Python 3.10+、PowerShell 5.1，以及本仓库的兼容 AIRI wrapper/控制台。把本目录源码部署到 `<base>/runtime/airi-aliyun-tts`，保留全部 `.py` 和 `.ps1`；控制台使用对应版本的 `aliyun_bridge.py`、profiles/catalog/server 与网页模块。不要把自己的 `private/`、token、state 或声音文件提交到仓库。

1. 在控制台的“角色声音”选择“阿里云 · 在线语音”，打开配置框；当前声音保持原样。
2. 选择密钥地域并在本机密码框填写自己的百炼 API Key。简易模式默认 `qwen3-tts-flash` / `Serena`，不附加情绪或语速参数。
3. 需要语气说明时展开高级选项，选择 `qwen-audio-3.1-tts-flash`、兼容音色，并从自己的百炼控制台复制对应地域的 API Host。不要填虚构的 `default` 业务空间，也不要把 Serena 用于这个模型。
4. 保存，再点“试听测速”。它只发送一条固定原创中文句，返回可播 WAV，并分别报告云端首音频块、完整可播文件与音频时长。
5. 试听成功后，“使用这个方案”只更新控制台草稿；点击原“应用并启动/重启 AIRI”才切换实际 provider。可选回 Windows 慧慧，再执行相同应用操作。

云端 Key 仅以当前 Windows 用户 DPAPI 密文保存在本机。AIRI provider 只拿独立的 loopback token。保存 Aliyun 设置不会改选中的语音方案；若已在使用 Aliyun，保存音色/语气后从下一句生效。

启动模板只在全局或受管理卡选中9949时启动该服务。切回本地声音时只停止通过严格身份核对的 owned9949。完整停止包含9949；`KeepServices` 保留它。单独检查：

```powershell
& '<base>\runtime\airi-aliyun-tts\health.ps1'
```

可用 `AIRI_ALIYUN_TTS_PYTHON` 指定已有解释器。启动器先解析 venv 的真实基础解释器再启动标准库服务，避免 Windows venv redirector 创建第二个 Python 导致 PID 身份核对失败。控制台模块可用 `AIRI_ALIYUN_TTS_ROOT` 指向另一个源码目录；随包的一键启动模板仍按上述标准 runtime 布局部署。

## 已测与未测

- [25项隔离adapter测试](verification-adapter.json)：临时假密钥的真实DPAPI、假SSE/HTTP、PCM/WAV、鉴权、错误与取消；真实云请求0。
- [真实Windows生命周期](verification-lifecycle-live.json)：启动、重复启动同实例、健康检查和停止通过；无真实Key，其他服务与AIRI设置不变。
- [控制台14项隔离测试](../../control-center/verification-aliyun-console.json)：密码不回显、状态/试听/样例、并发与revision、provider别名及网页渲染边界；真实云请求0。

0.2.2的无Key基线只验证本地程序。0.2.3另完成一次3.1真实固定句API连通：首音频1792.475ms、完整可播WAV2375.227ms、音频3.28秒。它只证明该次账号/网络/模型的连通；音质比较、持续/多样本速度、实际AIRI出声仍未验证。当前 AIRI 兼容TTS先等待完整小句的 ArrayBuffer，再播放；云端首包时间不能当作人物开口时间或麦克风到扬声器总延迟。保留现有本地声音，测试成功并明确应用后再切换。

接口细节、主文档和格式限制见[verified-method.md](verified-method.md)；控制台流程见[方法说明](../../control-center/aliyun-console-verified.md)。

[真实控制台浏览器验收](../../control-center/verification-aliyun-console-production.json)另已通过：下拉打开配置、不切换声音，地域/音色/高级语气可操作，无Key时测试与应用禁用；关闭后仍保留系统声音、AIRI停止和屏幕关闭。此验证未填写凭证或触发云请求。

0.2.3兼容性方法：[云Key格式与47项合成验证](key-validation.md)、[完成SSE后的已知WAV占位头与43项验证](streaming-wav.md)、[真实API单句结果](verification-cloud-live.json)。

## 实际应用与启动范围

[0.2.3应用/启动报告](verification-airi-startup-live.json)确认全局与三张受管理卡的speech选择已应用Aliyun，本地9B聊天和识别保持；helper/profile、活动3D与idle就绪，原生窗口及“正在听”状态已观察，屏幕观察关闭。这个部署当时登录自启关闭；它与历史自启工具验证是不同状态，不自动更改。

另一次不同短句通过9949代理返回HTTP200，完整1.6秒WAV等待2184.301ms，只在内存验证而未播放。它与前述3.28秒样例内容/路径不同，不能相减得到adapter开销或视为同题比较。启动时曾出现一次未定位的窗口退出，重开后当前就绪；连续会话稳定性、用户实聊、实际出声、口型与麦克风到扬声器延迟仍未验收。没有公开原生截图、录音或私人配置。
