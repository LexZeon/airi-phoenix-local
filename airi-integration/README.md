# 已验证的 AIRI 注册与 SDK 文本观察

这些小型源码快照来自当前已安装AIRI的实际接入路径；它们借用目标应用已有的Pinia store/
server SDK，不包含完整AIRI、Core、私有配置、已登录profile或模型文件。
升级AIRI后应重新核对store与SDK契约，不能认为内部字段长期不变。

## 私有 PMX 模型注册成独立3D卡

适用：用户已提供有权本机使用的模型及其纹理，当前AIRI支持`pmx-zip`，主应用已启动。
按该模型自己的来源和readme处理；其他配布页面的限制不能自动套用来推定它的许可。
模型/纹理/ZIP留私有目录，不进入本工具的Git或发布包。

验证过的路径是：

1. 模型与相对纹理路径打成UTF-8 ZIP，包中选择唯一PMX入口。本机受测私有包为16,493,075字节。
2. 在真实渲染器MAIN world等待现有`airi-card`与`display-models` Pinia store就绪。
3. `const model = await displayStore.addDisplayModel('pmx-zip', file)`，然后用`getDisplayModel(model.id)`确认持久化。
4. 清除导入卡上外来的avatar引用，`await cardStore.addCard(card, 'import', model.id)`；验证卡的avatar类型是`mmd`。
5. 根据用户选择调用`activateCard(cardId)`。不要手写一个从未注册的displayModelId，也不要直接修改运行中的IndexedDB。

[character-3d-bootstrap.js](character-3d-bootstrap.js)保留了这条实际调用链，包括受管理标记、
模型哈希检查、重复使用已有导入、版本更新及保留其他卡。调用者需要在自己已授权的renderer
MAIN world提供可信配置；这不是双击就能连接任意AIRI的外部注入器，也不会自行读取模型或凭据。
该快照的受控模型URL限定`http://127.0.0.1:9943/...`，要求本机wrapper提供只读的命名资源路由。

实际状态见[私有3D卡验证](verification/private-3d-card.json)：真实Pinia注册/激活通过，完整3D在
透明AIRI桌宠前台可见，听音状态可见，9941/9942/9945就绪，屏幕发布2、失败0、renderer错误0。
**只是模型显示和接卡已验证**；原创自然手臂/待机已通过原生VMD解析、独立实际MMDScene、主app导入和前台可见检查，见[动作工具](../mmd-tools/README.md)；不把这一结果推广到其他骨架或物理。

快照关闭MMD物理以保持该受测配置稳定。MMD physics是应用级store设置，不是每卡字段；
它不更改Live2D模型位置或控制。调用者应把这一全局影响计入自己的配置选择。

## SDK合成文本观察：语音因果关联未证实

适用：已运行的AIRI、现有本地9B与Qwen9945服务，以及合法可读的本机server-channel配置。
[验证器](verification/verify-app-llm-tts.mjs)只发送固定原创短测试文本，使用独立synthetic binding，
只观察该binding的回复事件和TTS请求计数，不保存其他聊天或回复正文，不打印鉴权令牌。

```powershell
$env:AIRI_COMPANIONS_ROOT = 'C:\path\to\deployment'
$env:APP_USER_DATA_PATH = 'C:\path\to\private\airi-data'
$env:AIRI_SERVER_SDK_PATH = 'C:\path\to\airi\packages\server-sdk\dist\index.mjs'
$env:AIRI_TEST_TTS_HEALTH = 'http://127.0.0.1:9945/health'
node airi-integration/verification/verify-app-llm-tts.mjs
```

`AIRI_TEST_TTS_HEALTH`只接受本机9942或9945 `/health`。默认等待180秒，另可配置
`AIRI_TEST_TIMEOUT_MS`与`SERVER_CHANNEL_PORT`。验证报告仅保存计数、布尔值和错误种类。
当前所测运行时没有注册`chat-ingestion` consumer，受测路径用structured module destination
加broadcast到AIRI自己的peer；脚本可用`AIRI_TEST_DELIVERY=consumer-group`检查相应诊断，
没有consumer不能误报为通过。

[历史报告](verification/app-llm-qwen-tts.json)最初被误标为声链PASS，现明确降为INCONCLUSIVE：匹配message/complete各1、预期短语出现，只证明该synthetic binding的完整文本回复被观察。同期全局TTS请求增加1不能证明由该binding触发，可能来自并行的其他请求。38970ms是旧观察总耗时，不是TTFT、TTFA或端到端播放延迟。

已核对的当前编译路径中，`overrides.binding`创建外部scene会话，`speaks=false`，不通过host播报gate。SDK assistant message事件在generation完成后触发，不是流式首token。公开验证器现在只报告`text-reply-observed`，始终标语音因果INCONCLUSIVE，不再以全局TTS delta决定成功。后续严格声链验收需要正确的host路径与精确synthetic request/TTS关联，尚未在这份工具中实现。

独立直接HTTP TTS请求返回合法WAV的验证仍有效，但不因此证明AIRI的文本消息已进入该请求。用户实际听到声音是另一类体验证据，也不能倒推这份scene测试的因果关系。麦克风采集、声卡实际回放及人物口型/表情仍分层验收。

端到端慢交互排查由用户安排在其他任务完成后进行。保留当前配置，先测候选后给选择；线上未测/无凭据一律UNMEASURED。

## 窗口内平移：源码核实，尚未真人拖动验收

受测AIRI0.12.0的MMD.vue启用OrbitControls：右键拖动或Ctrl/Shift+左键为相机PAN，普通左键ROTATE，滚轮缩放。这是相机临时操作，不是拖动整个操作系统窗口。持久模型位置可在设置→模型→MMD→场景的position.x/y调整，store使用`settings/mmd/position`本地存储。

上述按已安装AIRI/three-stdlib源码核实，尚未计作用户实拖验收。相机平移和持久模型X/Y是两层状态；修改模型位置不应同时宣称修好了相机或原生窗口拖动。
