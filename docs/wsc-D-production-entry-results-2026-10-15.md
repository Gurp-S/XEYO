# 306：生产投影与原生Read验收入口收尾

用户要求讨论新对话后仍完成正在做的工作。本项已完成所属评测入口：复用既有actor/厂商帧恢复，通过真实commit、生产fold/project、原生Read和恢复发射获得可审查输入。它不是新的语义压缩机制，也不替换WSC生产行为；新四臂/Hybrid讨论另见配套三轮复审。

## 实现与检查

- `python/evals/wsc_production_continuation.py`：构建原生store/working/registry，实际TodoWrite事务及转录，沿用force_compact/project_for_model/head_store，验证确实发布而非仅声明成功；重启读回转录和working。Read只可读当前publication精确对象集合，私有oracle/预备请求/key不在能力范围。
- `python/evals/wsc_native_actor_result.py`：原生ToolResult用产品tool_result_message直接传递正文/is_error/媒体/execution；老字典路线维持旧消息字节形状。
- `python/evals/wsc_task_actor_candidate.py`：仅将工具分派接上述适配，不改变事件检查点、未知结果拒绝自动重放、调用额度和原评分。
- `python/tests/wsc/test_production_continuation.py`：**9/9定向测试**；其中一项实际执行既有actor的**13/13旧合同**，不可再相加冒称22个独立pytest测试。

首轮8通过1失败是图片夹具使用AA==非法PNG，产品media_store正确拒绝；保留first.xml，改用有效1像素PNG后9/9。没有绕过厂商规范化或图片校验。这个检查只证明图像字节/结果帧经过编码，不是模型读懂图像或完整媒体冷召回验收。

## 两份真实来源的免费重建

来源沿用206原始JSONL和各自已经付费生成的D声明。将已有合法声明重新经当前原生事务提交；没有重新生成语义摘要，没有修改旧模型输出，不称为新模型样本。来源初始条数包含原D声明，实际提交再追加新调用/回执。

| 当前同一估算器 | long_noise_task | completed_waiting_authority |
|---|---:|---:|
| 初始source rows（含原D声明） | 1649 | 135 |
| 实际退休region_end / cursor | 1644 | 130 |
| native checkpoint估算tokens | 2252 | 2082 |
| 生产热头估算tokens | 18740 | 17048 |
| 完整请求估算tokens（含本实验Read schema） | 34843 | 29204 |
| 真实原生提交/发布 | 通过 | 通过 |
| 实际Read返回非错误正文 | 通过 | 通过 |
| 重启source及完整投影相同 | 通过 | 通过 |

估算器为deepseek_v41_text_reference_estimate，不是厂商计数收据；不得和282的UTF8估算值直接相减。完整请求包含真实生产尾部，不能用checkpoint大小冒充。没有T_now/完整GUI工具表/query_loop调度/85%压力测试，因此这里的“完整”指已声明的本评测输入边界，不是整个现场XEYO请求。

两份来源原始SHA分别b767a4083dcc9b33ff926016cc4c355065839f85f108c2ebf3096466e7a65649、de8259be88f5e0cea5b662d70623f6c9e90b2614ffd0152e9f933c74d4457e39；306/rebuild-report.json保留来源、源码hash、返回结果。各case目录含完整projection、规范化request、实际Read与原生转录；source-code存封存实现。

## 已完成和未完成

- [x] 本项评测入口实现、9项测试及13项旧actor合同、两真实来源的实际提交/投影/读取/重启重建；全部0新API、0费用。
- [x] 旧dict协议不改变；原生Read错误、能力边界、正文不被再次JSON编码、取消pending和原始厂商帧恢复经检查。
- [ ] 新模型在此真实投影下的实际continuation/task success，仍待新实验；重建合法不等于语义正确。
- [ ] 文本精确证据的Need→Trigger→Locate→Read→Use、实际媒体理解、多代/现场/原228/A1验收不由本项关闭。

新增入口直接供后续真实评测使用，不增加产品flag或持久格式，不修改冻结头或旧会话原文。当前没有为旧的直接JSON路线继续扩大付费样本；下一步实验设计先按用户提供的新假设拆开prompt、表示、最终投影和安全层。Goal保持active。
