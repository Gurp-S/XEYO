# P1：真实 provider 帧适配及任务校准——三轮复审

具体范围：独立付费评测 transport 的真实 assistant 原帧回传，复用既有请求构造、OpenAI chunk解析和预算/停止流水；之后用270两域完整来源校准实际产物任务。原生REQUEST、schema、Guard、提交协议、生产模型默认和冻结头不改。

## 第一轮：协议根因与复用

原 `MeteredNative` 明确删除请求 reasoning_content、不产生 reasoning_delta，for_handoff返回基类；启用thinking参数无法证明原生交接保真。267 ReplayModel修复typed帧，但tool参数会经过loads/dumps，不能承诺原provider argument字符串字节相同。

否决继续给旧MeteredNative加一处thinking开关；也否决用手写占位思考绕过400。v1：独立adapter保存成功provider response原assistant message，只对完全相同call ID顺序、工具名和解析后参数的本次专用续接回填原帧。实际chunk解码复用 `_openai_common`；预算、原请求文件和usage仍由StopAwareCalls记账。

## 第二轮：边界、失败和状态所有者

否决同时依赖typed ReplayModel和raw-frame registry承担同一回放职责：旁路transport只保留一份本次原response帧；本次无需叠267包装。每个请求使用现有 `_build_body`，随后在wire层匹配工具调用的身份/参数后回填同一原始provider帧，不改其他消息。无工具的最终回复没有续接帧。

额度子客户端共享已成功帧与计数；usage在结束判断前存入实际客户端，length/refusal/filter、取消、异常不发布完整帧。原JSON参数字符串、正文、reasoning保持原值；非对象/非法JSON使用现有解析器语义，不自创归一化。对同ID不同参数/工具或重复帧拒绝，不修正模型输出。

完整来源任务校准使用ArtifactSink物理范围与外部oracle；不调用全局工具、不凭done通过、不允许失败后填gold。Thinking统一enabled作为明确评测条件，所有后续A1/D同模式；不是生产默认变更。270原disabled准备材料保留，新的enabled调用单独标记，不能冒充与旧实验同期排名。

## 第三轮：可证伪、公平性和费用

先零API验证原JSON字符串/思考/正文/多工具顺序、子额度、截断usage、不完整帧、同ID参数变化及原生generate实际读取/拒绝路径。失败则不外发。直接完整来源两域各最多3个actor调用、4096输出，工具相同；它们只检查任务可识别性，不比较WSC方法或证明压缩质量。

随后适配器可用于实际原生交接/A1同源任务对照；本次若生成输出、scope/state schema或恢复接口要改，另作各自三轮。拒绝首轮就花钱跑两域十代；先证明未压缩能做对，避免继续为资料不足/模型错误优化WSC。

复用既有预算Calls/StopAwareCalls，HTTP不重试，单次<=2.5元，usage未知保留预留；402/准入失败停止队列。零人为预热，单次小输入；成功任务的实际工具回执、产物、每次request SHA/usage与总调用分开留存。保留旧失败，不重新发送255/260已失败请求。

准入：旁路协议合同通过与实际产物成功仍不自动并入。原228、语义、长期、媒体及生产重建完整Goal不变。范围/时序假设被推翻则重做三轮。
