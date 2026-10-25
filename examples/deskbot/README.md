# DeskBot：独立配置与 motion3 示例

这是从随包原创 robot atlas 重新配置的几何角色，不是菲欧妮。它有 8 drawable、7 个参数、4 个表情，左右眼独立开闭，嘴开合、浅头部侧倾和呼吸。素材及原创程序为 MIT，无 Core 和其他角色图像。

从包根目录运行（`--out`必须不存在或为空）：

```text
python examples/deskbot/rebuild.py --out work/deskbot-001 --core-file /path/to/existing/Core.js --node-executable node
```

脚本依次 inspect/build，再添加本项目自己的 Idle 和 Demo motion3，随后调用 Core 验证并重打 `DeskBot.zip`。省略 `--core-file`可以构建，但报告明确为未做 Core 验证。`rebuild-report.json`记录各阶段、运行文件和未做的检查。现有输出不会覆盖。

`project.json`和`artwork/parts.png`可直接编辑，`sources.json`记录原创来源。`rebuild.py`中的动作曲线是标准线性 motion3 后处理数据；通用 `rig-tools`项目 schema 没有 motion 编排字段。先前独立验收实际用 CubismMotion evaluator 播放过 Idle/Demo，并做了 WebGL 图像检查；公开最新版仍需要使用者在自己的目标软件验收。

通用 `render`命令可借用用户已有 AIRI 编译输出/Electron/Core生成隔离离屏图像。它不等同于实际 AIRI 桌面导入、ACT 表情调用或语音 lip sync；这些未在本示例中自动执行。模型是扁平几何，有浅二维移动，不含3D转面、手臂动作、物理或 `.cmo3`编辑工程。
