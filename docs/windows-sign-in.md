# Windows 登录后启动 AIRI 和选中的本地服务

适用于已经能用 `launchers/airi-start.ps1` 正常打开的部署。它注册当前用户的 Startup 快捷方式，发生在**用户登录 Windows 后**，不在登录前运行，也不新增系统服务或管理员任务。

先单独验证一键启动。该启动器检查本地聊天、识别和所选语音服务的进程身份及健康状态，再打开 AIRI；已有同一应用时复用。开机入口不另写一套模型启动命令，避免两套默认参数或重复加载。未安装的模型和运行环境不会因此自动补齐。

```powershell
& .\launchers\airi-autostart.ps1 -Action Enable
& .\launchers\airi-autostart.ps1 -Action Status
```

若只下载本工具包而实际启动器在另一个部署根目录，显式传入 `-Launcher 'D:\MyAiri\launchers\airi-start.ps1'`。该路径必须是已有、自己信任的启动器。PowerShell 使用 `-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ... -NoBrowser`，快捷方式工作目录设为该部署根目录；它不修改系统执行策略。`-NoBrowser` 避免启动失败时弹出模态对话框，错误仍留在原启动器的本地日志。

关闭此入口：

```powershell
& .\launchers\airi-autostart.ps1 -Action Disable
```

脚本只删除目标和参数都匹配的这一个快捷方式；同名但不属于该启动器的文件会拒绝覆盖或删除。注册命令本身不会运行启动器。Windows 设置曾禁用的 Startup 项可能继续禁用；查看输出中的 `windowsStartupState`，并在「设置 → 应用 → 启动」中核对。脚本不绕过该设置。

## 已验证的范围

- 本地现有启动入口已经注册到当前用户 Startup，回读了目标、完整参数、工作目录；注册前后正在运行的模型与桌面 PID 保持不变。
- 实际执行了已注册的隐藏窗口启动命令作为重复启动验收。第一次暴露该进程中 `Get-FileHash` 不可用；资产比较改用 `.NET SHA256` 文件流后重试 exit 0，服务监听进程创建时间仍早于测试，最终 health ready。详见[匿名启动命令报告](../airi-integration/offline-shell/verification/startup-command-verified.json)。这验证实际注册命令，不替代下一次 Windows 登录。
- 公开的通用脚本通过 PowerShell 语法检查，并在独立临时 Startup 目录验证创建、重复启用、状态回读与关闭；测试启动器故意设置为抛错，注册过程没有执行它。
- 这是快捷方式注册和既有启动器检查的证据，**没有用重启或注销 Windows 来冒充已完成下次真实登录验收**。真实登录时的加载速度、外设状态和窗口恢复需在下一次登录确认。
- 屏幕观察和电脑控制的默认值由 wrapper 的独立权限开关管理。开机启动应用不应顺便开启屏幕采集；见后续屏幕权限方法。

此脚本不附私人部署路径、快捷方式二进制、模型或用户配置。
