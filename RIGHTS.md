# 权利、依赖和公开范围

本项目是非官方 AIRI 角色制作工具及《绝区零》菲欧妮·蕾法爱菈制作记录，与 HoYoverse、Live2D、AIRI 或声优没有隶属或背书关系。名字、设定、官方美术及角色 IP 属于相应权利人。

| 内容 | 来源／许可与本包范围 |
| --- | --- |
| 原创代码、文档、提示词 | 根目录 MIT；作者署名 LexZeon。角色 IP 不因此转移。 |
| 原创几何 robot/DeskBot | 随包 MIT；无第三方角色、官方像素或 Core。 |
| 原创12秒骨骼待机VMD | 随包 MIT；由程序生成，只含旋转/微位移，不含用户PMX、纹理、第三方动作或头/眼/嘴/morph轨道。不同骨架需重新适配。 |
| MOC3 serializer | [Ludentes/py-moc3](https://github.com/Ludentes/py-moc3)，固定 `2fb112e11a2d495557cfd09fbea72015cbfd47c5`；完整 MIT 通知和文件哈希在 `rig-tools/vendor/py-moc3`。未带其他无统一许可角色案例。 |
| Live2D Core／SDK | 不打包，不自动下载。用户提供合法取得的现有 Core；遵守 [Live2D 许可](https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html)。 |
| Qwen3-TTS | 适配代码 MIT；[上游程序](https://github.com/QwenLM/Qwen3-TTS)及 [CustomVoice 权重](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)采用各自 Apache-2.0；版本/哈希见 `voice/models.lock.json`。程序不附权重或第三方依赖二进制。 |
| 三段 WAV 样例 | 本地内置 Serena 配合原创风格描述与原创短测试文本的合成结果；没有声优参考录音、声线克隆或角色专属 speaker embedding。不得冒充声优、游戏台词或官方音频。 |
| 菲欧妮人设、表情配方 | 基于官方出处的简短原创转述与角色扮演设计；不是官方台词或官方情绪标签。出处和观察不等于素材再授权。 |
| 官图／官图派生纹理 | 只在本机研究和验收，不进入仓库或发布 ZIP。仅保留来源 URL、哈希、提示词、坐标和参数。 |
| 官方 MMD／3D 包 | 不打包。已核实的官方模之屋条目限制非视频用途及再配布；下载、修改、参考、桌宠用途和再配布必须分别核对，下载成功不等于可作桌宠。 |

官方模之屋账号为 [绝区零](https://www.aplaybox.com/u/352588796/model)；[常服](https://www.aplaybox.com/details/model/ruG9HuID3O8q)及 [两套时装](https://www.aplaybox.com/details/model/oZQiRK0WxZTV)仅作来源指针。记录时两条官方配布均不开放商业、再配布和非视频用途，正文另有限制。用户自己的正常登录下载不能扩展许可。第三方游戏提取／镜像条目标记较宽松，也不能替代原权利人的授权。

不发布官方模型、官方帧截图、故事板、立绘、声优录音、LoRA/其他权重、私人截图、个人聊天、API 密钥、令牌、已登录浏览器 profile、系统/应用配置或运行缓存。程序许可不意味着任何导出模型都能商用或再次授权；使用者应保留其实际来源的许可和署名。

以上模之屋许可记录只对应所链接的配布条目，不能据此推定用户另行提供的其他3D模型的权利或用途。用户自有本机模型按其附带readme与实际来源分别记录；它的本机显示测试不意味着仓库获得再配布许可，文件仍不上传。
