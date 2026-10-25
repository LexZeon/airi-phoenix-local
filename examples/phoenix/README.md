# 菲欧妮：来源、人设和本机制作配方

此目录不是可直接导入的最终角色模型。公开内容为原创转述的人设/对话规则、12 表情来源、提示词和参数/坐标。官方图、官图派生PNG/MOC3、官方3D模型和声优录音都不附带。

- `sources.json`：官方页面/视频链接、约±2秒的不精确故事板时间和原创观察。
- `character.json`：原创同人角色规则、12精确表情名、AIRI模块配置；默认本地Qwen语音Serena原创风格，非声优克隆。
- `rig-project.recipe.json`：本机常服的图层/原图特征polygon/参数配方。`local-assets`有意留空，本例缺来源素材时inspect应失败；不能把它作为开箱即用模型。
- `prompts/face-underlay-generation.json`与`eye-whites-generation.json`：当前保真小区域补绘记录。
- `prompts/base-generation.json`与`facial-generation.json`：旧v1被否决的正面重绘历史，非当前成品，也不附该画稿。

当前本机常服保持2347×1253原姿势，完成14 drawable/19参数/12表情：左右眨眼、独立裁切虹膜、口型、浅头动/呼吸、Head/Body HitAreas。中性RGBA与原图全等；实际AIRI WebGL离屏及Core133组合通过。官图2D实际桌面已可见，位置/12表情与语音联合验收仍在进行；站姿2D与两套时装待制作。另有用户自有3D前台显示已验证，作为独立卡，不包含其模型文件。公开只附sanitized数值报告，不附官图派生预览。

配方的`base/original/leftwhite/rightwhite`分别引用相同原图文件，仅在内存中按明确polygon做不同技术补底；`skin`和`whiteplate`来自外部图像工具。只有拥有相应使用权限的本地项目才应提供这些来源。不要为方便构建而从第三方镜像打包素材。可运行示例请改用`rig-tools/examples/robot`或`examples/deskbot`。
