# 有效制作路径、必要陷阱与验收状态

记录日期：2026-10-25。这里区分本机验证、通用程序发布和最终角色验收。

这是经过提炼的技术结论，保留失败只为解释已修正的方法和实际限制。操作步骤优先看[已验证手册](verified-paths.md)，不把聊天或完整调试流水作为仓库主体。

## 本地 AIRI 与已有模型复用

目标是 Windows on ARM 上的本地对话、中文语音、视觉上下文和角色表现。复用已有 Qwen3.5-9B-Q4_K_M GGUF、匹配的视觉投影、ARM64 CUDA llama.cpp、SenseVoice int8、FFmpeg 和创作环境。没有复制一份 9B 或改动另一个应用的全局 Python 环境。AIRI 部分桌面原生依赖只有 x64 版本，所以桌面使用 x64 Node/Electron 仿真，推理/语音仍为原生 ARM64 服务。

服务只监听回环。日常运行不拉取代码或权重；下载、更新和 GitHub 发布是单独的联网操作。AIRI VAD 的模型和准确版本 ONNX Runtime 资源在本地加载；曾修复 Transformers 3.8.1 动态加载器仍请求 jsDelivr 的问题，没有拿不匹配的新版 WASM 替换。

合成视觉测试图中的文字、颜色、形状识别通过。中文 WebM 识别、WAV/MP3 合成、TTS→ASR 回转和重复启动曾通过。早期SDK合成文本完成已观察，但全局TTS计数不能证明该binding触发语音；默认角色/工具提示超过原8K上下文，专用9B服务改32K后恢复。独立精简人物提示的一次文本测试约1175 tokens、5.7秒返回有效ACT，不能把它记作语音端到端延迟。屏幕上下文只在内存处理并保留最新摘要，制作记录不带私人屏幕截图。

## 官方资料、现成模型和表情

按官方角色页、代理人档案、版本公告和官方视频核对身份与性格。事实、视觉观察和原创演绎分开；未核对的年龄、生日、身高、完整剧情与台词不补造。12组表情出处、近似时间和原创观察在 [sources.json](../examples/phoenix/sources.json)。故事板约±2秒采样，不能称为精确视频帧；公开包不包含这些官方图片。

未找到可确认许可且可直接导入的完整菲欧妮 Live2D 运行包。后续通过官方 [模之屋账号](https://www.aplaybox.com/u/352588796/model)找到了[常服](https://www.aplaybox.com/details/model/ruG9HuID3O8q)与[两套时装MMD](https://www.aplaybox.com/details/model/oZQiRK0WxZTV)。它们是3D MMD，不是Live2D。官方条目限制商业、再配布、非视频用途，正文还有AI训练/生成数据集限制；本机正常登录下载/预览与桌宠授权是两回事。公开只保留链接和制作观察，不打包官方模型。游戏提取/镜像不能替代官方许可。

## 真正 MOC3 的技术路径

采用 [Ludentes/py-moc3](https://github.com/Ludentes/py-moc3) MIT serializer，固定提交 `2fb112e11a2d495557cfd09fbea72015cbfd47c5`；完整许可和文件哈希随包。没有采用其他包装仓库中无统一许可的角色案例。原CLI存在布局/计数与round-trip问题，所以编写独立配置驱动构建器：显式透明图层/atlas、网格、参数keyforms、原生mask、exp3、HitAreas和runtime ZIP。Core不随包发布。

早期Core几何通过后过早切入桌面，实际只显示放大手套和五官碎片。原因是UV序列化与Core/目标shader重复翻V。修复后实际AIRI Pixi/Cubism WebGL离屏显示完整人物，并加入Core UV原点断言和真实纹理渲染。CPU几何PASS不能替代纹理/视觉验收；候选之后不再自动激活到用户桌面。

## 画风漂移与保真修正

第一版ImageGen正面对称重绘偏幼圆脸，并省略了武器/焰翼；用户否决，未作为当前成品。其提示词只以被否决的过程历史保留，无图稿公开。

当前常服改用原2347×1253官图姿势与像素。只从外部补绘的小皮肤/眼白underlay，在精确眼、眉、嘴及虹膜polygon内技术采样；原睫毛/眼框、虹膜、眉和小嘴拆成部件。中性重组与完整原图RGBA逐像素全等，补丁外变化为0。没有整脸替换、对称化或重画服装、头发、武器与焰翼。

本机候选是14 drawable、19实际参数和12表情：左右眨眼、独立裁切虹膜在clip mask内跟瞳、原嘴浅仿射口型、眉、浅头动/身体/呼吸、Head/Body HitAreas。Core133组合通过；实际AIRI WebGL离屏29幅测试中12表情画面均不同。头动很浅（原图约3px水平、2.5px垂直、0.8度），无3D转面、手臂动画、螺旋眼、暗面发光或腮红实现声明。官图派生PNG/MOC3/ZIP及渲染图片都只留本机，公开只有sanitized数值与配方。

## 声音：从基础离线到原创表现风格

MeloTTS中文通用女声先完成离线链路，保留为轻量回退。后续采用官方Qwen3-TTS-12Hz-1.7B-CustomVoice内置Serena，加三种原创中文表演描述：温柔陪伴、微倦轻声、工作利落。没有用宋媛媛/藤田茜录音，没有克隆或专属声线embedding。

[voice](../voice/README.md)包含可复用服务与哈希锁、3段原创测试语音、API与队列/离线请求层报告。约4.52GB权重单独下载，匹配文件可复用，不打进本包。默认9945 `/v1/`。实际3段4.48–5.20秒音频耗时6.67–15.88秒；后续warm请求3.04秒音频与MP3返回约4.76秒。当前是整句批处理，首音等待整句生成，不能声称上游97ms流式延迟。API、8请求队列/第9拒绝、断开清理和后续并发句块都实测通过；听感相似度由使用者试听判断，不由波形测试决定。

## 让别的开发者与 AI agent 能接续

本包的Skill名为`airi-character-forge`。CLI输出稳定JSON，另有legacy MCP2025-11-25 stdio适配，不需要特定AI账号。语义生成由使用者agent自己的工具完成；程序不承诺任意单张图全自动分层。

独立agent用随包原创robot素材配置DeskBot，做左右blink、口型、4表情和Idle/Demo，并发现真实缺口：文档依赖缺失、schema未实际拒绝未知字段、缺运行素材时validate仍PASS。已补requirements/真实README链接、执行全schema约束、校验每条model3 runtime引用和参数，再运行Core。负例现分别返回exit2/4；这些修复有可重复测试。

通用schema仍不编排motion3；DeskBot的`rebuild.py`明确作为项目后处理添加两组动作，并可独立重建。验证器依赖自家build-manifest，不是任意第三方model3通用验证器。输出runtime MOC3而非Cubism Editor `.cmo3`。

角色卡导出器提供原生AIRI/CCv3/SillyTavernV2与带模型AIRI ZIP。精确表情名走真实ACT路径，例如`<|ACT {"expression":{"name":"E11_ClosedEyeSmile","duration":3}}|>`。卡导入才注册device-local display model；不伪造ID、不直接改运行中的IndexedDB。每张卡可能覆盖全局speech设置，ASR在所测AIRI版本为全局配置。代码兼容验证不等于实际桌面语音/表情验收。

## 尚待验收与制作

- 官图2D已在实际AIRI桌面可见，继续调整位置与联合验证人设、12表情、鼠标/眼睛、音频播放及lip sync。
- 按三张独立卡交付：官图2D、站姿2D和用户自有3D。3D前台显示已在本机确认；站姿2D已完成006眼位修正及原生小窗中性检查；完整native四向极值/独立眨眼未覆盖。模型文件不公开，来源/readme分别记录。
- 两套时装由用户明确暂缓，保留出处作可选参考，不列当前欠缺或阻塞。
- 全套目标配置实际停止/启动已通过，保留独立9931服务；更新后还需按新AIRI版本重验。
- 本机配置台已通过API/UI与三卡选择隔离回归；用户自有3D实际主app显示与原创自然待机可见。

公开ZIP是完整工具/配方/原创fixture包，不是已经完成全部服装的菲欧妮模型合集。排除Core、官方素材/派生纹理、官方3D包、权重、密钥、私人截图、聊天与浏览器profile。

## 持续记录与聊天贴纸工作项

用户新增持久约定：本聊天全部AIRI配置、修改和调试都要记录到GitHub。已写入根AGENTS与单独记录工作流；发布脱敏过程、可复用代码/模板、验证和官方素材URL/正常获取脚本，不上传私人数据或官方受限资产。

聊天界面“表情包/贴纸”设置与model3的12个面部表达是两套能力。贴纸工作优先核实官方资源和AIRI真实设置，分别记录配置与实际聊天显示结果；制备/导入代码与实际设置缩略图验收已接入，真实聊天选图仍另验，不能以Live2D表情已通过代替。

其他现有任务验收后已执行固定合成输入的分阶段HTTP与本地TTS候选比较，详见[选择表](speech-options.md)。默认保持；优化别名只供选择，真实VAD/声卡回放和严谨host关联未被HTTP计时替代。

## 已提炼的新接入方法

实际用户自有3D包经Pinia addDisplayModel('pmx-zip')→addCard(card,'import',model.id)→activateCard接卡成功，physics关闭，完整3D桌宠可见；原创自然手臂/待机已通过原生解析、独立渲染、主app导入和前台可见检查。受测API与限制见airi-integration。官方配布页面的用途标记只记录该条目，不能替用户另行提供文件的readme下结论，所有模型仍不公开。

历史38970ms记录只观察到独立synthetic binding的完整文本回复与同期全局TTS计数变化。源码核实该scene会话speaks=false，全局计数无法关联这条输入，故语音因果结论改为INCONCLUSIVE；SDK message/complete不是首token。独立HTTP返回合法WAV的测试仍有效，严格声链关联和物理播放分别验收。

聊天贴纸制备、官方来源查询与真实store helper已随代码公开；9官方帧静态PNG实际制备和重复一致通过，Pillow5+Node5测试通过。主app实际导入/设置/缩略图显示通过，真实聊天选图仍待验；图片与私有导入payload不公开。两套时装由用户明确暂缓，只保留来源，不作为当前欠缺或阻塞。

聊天贴纸实际原生设置页补验通过：启用ON、50%、12默认+9新增，滚到新增项能看到多张官方帧缩略图。验证覆盖真实导入/持久化/设置与缩略图渲染，不等于真实聊天已选图。含私人聊天overlay的本机截图不公开。
