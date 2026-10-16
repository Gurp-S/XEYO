# 同源billion-context对照209

结论：这两份会话中，billion-context原生内核完成了真实模型compress调用、建块、保留最近原文和投影；离线所覆盖输入文本可解压。续接成绩没有追上D/新A1。保持D/A竞争，E缺完整新鲜状态前提，DSH不再追加测试。不能据两例宣布billion-context在所有任务、长期缓存或小窗口运行上无价值。

## 同源数据

| 指标 | D 交接＋薄层（206） | 新A1 Codex本地方法（208） | G billion-context（209） |
|---|---:|---:|---:|
| 完整热层tokens：长任务 | 2,440 | 7,957 | 3,657 |
| 完整热层tokens：另一例 | 2,267 | 1,322 | 4,723 |
| 完整初始请求含工具tokens：长/短 | 旧报告未计工具 | 12,921 / 5,823 | 8,907 / 9,510 |
| 事实正确，排除原范围歧义项 | 12/13 | 13/13 | 3/5；另一例NA |
| 活跃约束正确 | 6/6 | 6/6 | 3/4；另一例NA |
| 具体值正确，非冷召回证明 | 7/7 | 7/7 | 2/3；另一例NA |
| 精确80字符冷召回 | 0/2 | 0/2 | 0/2 |
| 正确冷原文前缀恢复 | 0/2 | 1/2 | 0/2 |
| 最终答案 | 2/2 | 2/2 | 1/2 |
| 主续接模型调用 | 2 | 6 | 6 |
| Read成功/调用 | 未调用 | 4/4 | 4/4 |
| 严格只读续接任务通过 | 0/2 | 0/2 | 0/2 |
| 有效来源引用/提供引用 | 12/12 | 2/3 | 0/4；另一例无答案 |

G长例输出的三个明确事实均正确，两项留为null，不能说其余都是错误断言。GUI无最终答案记NA，不强算8个事实全错。事实/约束总分不是泛化可靠性、完整代码任务执行或论文结论。旧各臂没有重跑，数值在新的aggregate-report.json中并列保留。

## 实际使用的源码和边界

使用原作者`ranxianglei/billion-context`，固定提交`623d3078c9dad60d2c1b030225995dc66d3a3dd8`，包0.1.196、内置acp-kernel0.0.121；未使用Tyan66666/billion-context-dsh或dsh-hypercompact。

官方源码：[内核](https://github.com/ranxianglei/billion-context/tree/623d3078c9dad60d2c1b030225995dc66d3a3dd8/kernel)、[compress工具](https://github.com/ranxianglei/billion-context/blob/623d3078c9dad60d2c1b030225995dc66d3a3dd8/kernel/src/compress-tools.ts)。仅用esbuild打包原内核与OpenAI编解码，未修改vendor源码。执行原openaiToCore、createCore/processTurn、原compress prompt/schema、parseCompressArgs、applyCompression、coreToOpenai以及collectBlockContent，不手写替代摘要或替代投影。

两份来源与206/208完全相同：1647/133条重建消息，经同一既有C0/C1与中断调用wire适配输入。真实模型各调用一次compress，模型填写range和摘要，原内核各创建1个T1块。摘要字符数6782/6085，均低于原maxSummaryLength20000；原默认recent5条/5000估算tokens保护保留。为固定同一7/8条原尾部，调用者把对应12/14个CoreMessage refs加入原soft-protection参数集合，内核使用已有carve与调用配对机制保留它们；剔除共同尾部后剩余原生热内容＋同一外部尾部一起评测，不重复保留尾部。没有额外调用模型修摘要。

生成是明确请求compress并指定tool_choice的受控单次操作，8192输出额度；modelContextLimit=1048576、processTurn tokenCount=0用于该同源语义对照。没有声称测到了原生自动触发、100K小窗口运行、多次增量压缩、T2/T3晋升、完整代理服务端持久恢复、长期缓存净收益。内核默认CCR/absorb/crush保持关闭。不能拿这轮替代原项目全功能运行。

续接Flash thinking disabled、temperature0、1536输出、每例最多4调用，原问题/gold及Read schema不变。额外提供原decompress/search_context/acp_status schema，采用原内核内容收集、搜索和状态函数；本轮模型没有调用这些额外工具。宿主文件导出只允许新实验目录内的新文件。内联decompress/搜索宿主适配不是完整proxy会话恢复实现，不能声称完整原生产品验收。源原文归档仍可由与其他臂相同的Read读取。

## 失败归因

长例读取共同原文归档成功，随后返回部分当前事实；cold_excerpt选择了第一条用户消息而非指定source_index3的工具结果。历史53的未经证实状态与第二批原子身份要求留为未知。没有选择旧ChatGPT目标，但完整引用0/4通过。这是本次模型的采用/定位/引用输出表现，不能等同于存档缺失。

GUI先两次Read成功，再请求未提供的Bash。评测器原先在未知工具处停止，保留原回执后，用中性`Tool unavailable: Bash`结果消费这个已有请求，再做第4次模型调用（没有重发第3次请求，也没有超出原调用上限）。模型转回Read，仍未返回最终答案。第4次Read也执行成功，其结果独立保存为未被模型消费；没有第5次调用。这里有一次模型工具选择越界，不能解释成摘要内核崩溃或原文被删除。

离线原生解压核对：被块覆盖的3146/202个CoreMessage，所有原text均出现在full内容收集中；native-state前后原messages序列相同。该保证仅针对已有C0/C1适配后的内核输入，不声称还原适配前所有原消息格式或源ID。完整共同source.jsonl副本2/2与旧实验字节一致，原最近尾部2/2保留，固定代普通追加前缀2/2一致。Read中文另做核对：第一条用户原文出现在实际Read结果、无replacement字符，避免把终端显示乱码错认成模型输入损坏。

## 成本

本轮8次API请求，8份usage，无HTTP自动重试。生成峰价估算2.276915元，有效续接0.096852元，合计2.373767元。累计授权12元，保守预算余1.194495元，原无usage预留没有释放。价格仍沿用miss2/hit0.04/output8元每百万的历史峰价估算，不是实际账单。

生成长例prompt1032713、output3596、hit3072；短例prompt83663、output2677、hit0。生成两请求同usage全hit情景费用约0.094839元，不能把此次2.276915元冷生成成本称为方法固有成本，尤其不能和208暖缓存A1直接比较节省率。

主续接input105857、hit62848、output1040，加权命中59.37%；短样本、不同前缀与缓存初态不能验收97%，也不能据此否定原项目长期命中声明。费用线不改变本轮以任务续接质量为先的排序。

## 当前方向

继续比较D与新A1；暂不把G并入默认，也不继续追加DSH。后续若用户继续授权，重点是D/A同等任务质量、精确召回与引用、未参与设计的新会话、多次压缩与恢复。E须先具备完整且新鲜的提交状态才有有效对照。本轮没有修改生产代码、冻结前缀或线上会话，原优化Goal保持暂停。

证据：`_wsc_out/wsc-billion-209/`下protocol/prepare、G-generation-report.json、两例G-apply-report.json、evaluation-report.json、resume-report.json、terminal-tool-report.json、offline-recovery-report.json、aggregate-report.json。API输入与返回均留存；不存在为了通过评分而重新生成摘要或改变gold。
