# 272–276：机械身份、原provider帧与实际任务产物

本轮继续完整D优化Goal，平台当前查询为active。用户方案U1–U6、代理S1–S9全部保留；新发现的评测缺陷也单列。每项变更有独立三轮复审，未将本轮合同/校准替代语义质量、长期稳定性或生产验收。

## 272：原型 phase 身份缺口前后对照

复审见 `wsc-D-phase-identity-review-2026-10-14.md`。新 eval 模块 `wsc_mechanical_guard_candidate.py` 接受来自已提交原生快照的task/baseline/phase IDs，预检PHASE引用，再调用原commit_candidate；候选不能自创registry。原source/hash/lifecycle及AD1逐项保留不变，新增预检失败时整次保留旧checkpoint。

旧28探针原样构造，并确认重新运行旧guard与原封存报告完全相同、旧报告字节未变。相同候选前后结果：

| 项目 | 旧guard | phase旁路 |
|---|---:|---:|
| 机械目标状态保护 | 18/22 | 22/22 |
| 不存在phase保护 | 0/4 | 4/4 |
| 语义探针 | 6项未验证 | 6项未验证，接受行为未改 |

补充16/16合同包括合法phase、新阶段外部登记、跨task/旧baseline、重复/空身份、伪造自有registry、hash保护、legacy TASK及PARTIAL结果口径。没有用拒绝所有变更换保护率。

这是AD原型的机械补缺，不是生产runtime phase registry或fact/phase version实现，不覆盖EXECUTION/FILE_VERSION范围，也不证明语义意图。U1报告分责已实现旁路；U6完整registry、U2epistemic、U3transition及U4原anchor呈现仍未完成。热层增加0、API0，未并入。

## 273/275：专用交接的真实provider帧

复审见 `wsc-D-provider-frame-review-2026-10-14.md`。独立 `ProviderFrameModel` 保存本次完成provider response的原assistant帧，匹配原call ID顺序、工具名与解析后参数后，在wire层恢复原正文、reasoning_content及argument字符串。复用现有OpenAI chunk解析、请求构造、预算和停止流水；不改变REQUEST/schema/Guard，不用占位思考，不与267再叠第二个回放权威。

273零API16/16协议合同，包含实际native generate读取/拒绝路径前后对照、多工具顺序、非法/non-object参数、子额度、截断usage、流未消费完、取消和身份冲突。仅provider形状fixture的协议证据。

275再检查6份实际官方DeepSeek请求：6次本次已付费工具帧回传均逐字段等于其原response assistant帧，原reasoning/body/argument字符串未改。源请求SHA逐次一致。它证明本次评测transport回放保真，不证明真实生产SSE链路修复、交接语义提升或长期任务成功；仍不并入生产。

## 275：完整来源实际文件任务校准

复用270两域初始来源/任务/工具，唯一评测条件改变为thinking=enabled；4096输出、每域最多3次请求，HTTP重试0。没有压缩、没有修改D提示词、没有更改旧270材料或事后gold，不把它当成A1/D排名。

- 素材清单：模型实际生成正确result.json，外部精确字段/值/类型验收通过；但写入工具随后AssertionError，正常续接未完成。
- 配置单位转换：3次调用后未生成文件，冷读参数多次遗漏offset/query；未压缩完整来源已经存在，无证据归为WSC丢失。模型调用次数上限与界面失配单列，不能填成所有语义字段错误。
- 正确实际产物1/2；正常完整工具续接0/2。仅两个合成领域，不是两份真实生产会话的压缩验收。

6次API、6份usage，估算费用0.02607976元，单次最大0.007032元。实际hit9344/miss5449，输入命中63.165%；这是本轮短请求样本，不是全项目命中率或净收益结论。按既有流水费率估算，未知旧费用保留，无人为预热或HTTP重试。

## 276：自己的评测缺陷修复，不改旧成绩

三轮复审见 `wsc-D-artifact-byte-review-2026-10-14.md`。结构性根因：原ArtifactSink选用Windows文本原子写入，LF转CRLF，随后原字节校验失败。271紧凑JSON合同遗漏了多行覆盖。正确文件已出现但receipt失败，不应归为模型或WSC错误。

只为本次触碰抽离ArtifactSink._publish；默认仍旧行为。新ExactArtifactSink在相同参数验证、范围、attempt记录与receipt路径中复用 `rewind.service._write_atomic` binary发布，一次写入，UTF8字节原样，不新增协调器/生产状态。

重放已经付费的真实模型ArtifactWrite参数：旧发布确实写成正确任务产物但抛错；候选原字节成功且receipt SHA一致。另含LF、CRLF、Unicode、NUL、空内容、replace失败旧文件/临时文件、错误数据、越界与取消尝试，共12/12零API合同。旧275成绩和错误不改，离线重放不是新模型成功。新prepare将使用新的源码身份，270封存源码在271、275中保留，不能拿它当当前代码重新运行。

274曾在读取UTF8报告时被Windows默认GBK拒绝，发生在创建API Calls及请求准备前，API0；275使用明确UTF8。失败记录保留。

## 固定待办与并入边界

- [x] 原型不存在phase的机械缺口旁路，22/22保护；语义6项仍未验证。
- [x] 独立provider帧16合同和6次真实回传核验；生产流式/恢复仍未完成。
- [x] 两域完整来源实际产物校准；未完成任务不算通过。
- [x] 自己引入的ArtifactWrite多行字节缺陷旁路12合同及已付费参数重放，无API重跑。
- [ ] 本轮发现actor函数在异常前的局部activity/pending没有持续存入report；已付费原请求/响应及write attempts仍保留。后续驱动需按工具完成事件保存回执，不把局部trace丢失误判为模型/引擎的执行事实丢失。
- [ ] 用修复后的可信同一actor验收D/A1，保留正常工具调用条件与失败原文/旧状态；完整来源未通过的配置任务先区分额度、工具接口和模型使用。
- [ ] U2/U3/U4/U5/U6完整状态合同与身份所有权逐项三轮/旁路对照；不能因本轮22/22就宣称全机械协议100%。
- [ ] S2–S9、原228底线、独立保留任务、1/3/5/10与异常矩阵、精确冷/媒体使用、生产重建及质量达到A1都未完成。

生产并入0，新的原型/transport/写入候选全部旁路。冻结头未动，旧台账只追加。Goal active且未完成，顺序仍按六轴合同，不因合同数量或产物入口修复收窄目标。
