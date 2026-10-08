# 批次33：未折叠工具回执不再被历史层二次截短

## 根因与结构规则

旧KEEP/C2尾部仍通过 `engine.compact._project_tool_result_content`，可按8192字符截短，或经尺寸prune/offload替换。工具已经按自身/registry输出预算返回，原结果又被历史层缩短，模型虽选择KEEP仍失去已观察内容。真实源中的一条Read就是交接提示词文档，不只是无关日志。

规则：模型拥有历史折叠时机的旁路开启时，未冻结结果保留已提交工具回执原文；执行层的单工具预算和原始spill保持。历史折叠/退休由明确模型请求或完整请求容量保护执行，不通过单条历史结果长度绕开。冻结区沿用原表示，不回填旧头，不增加全历史用户原话层。

## 修改文件

- 新 `python/memory/wsc_unfolded_results.py`：旁路与未冻结边界判据。
- `python/engine/compact.py`：在非冻结结果上先应用判据，直接保留raw，统一覆盖全量/incremental和native WSC尾部；冻结表示不变。
- 新 `python/tests/wsc/test_unfolded_results.py`：成功/错误回执、尺寸/offload开关、增量/native尾部、冻结区及registry真实spill回读。
- 新 `python/evals/wsc_unfolded_source_ab.py`：相同重建头、相同真实源尾部，只切换历史投影政策，逐来源位置/调用ID核验已提交正文。
- 本证据、唯一总账与追加账本。

## 回归

5条新增；定向C0和时机链路15 passed。扩展：`tests/wsc tests/test_compact.py tests/test_spill.py tests/test_spill_shadow.py tests/test_spill_prune_scope.py tests/test_runtime_c2.py`，1002 passed（36.49s）。不同批次选择不同集合，不能按1031→1002判断测试减少/失败，也不能相加。

## 真实会话重建对照

源为已有私有捕获 `_wsc_out/continuation-2026-10-08/source.jsonl`，2339行；SHA见原始report。新重建在明确选定pair-safe=2000的边界，生成一次WSC头及不可变冷视图，然后两臂复用同一头和尾部。不是恢复旧现场provider wire，不冒充原历史折叠时点。

命令（python目录）：`py -3.11 -m evals.wsc_unfolded_source_ab ../_wsc_out/continuation-2026-10-08/source.jsonl --output ../_wsc_out/unfolded-source-2026-10-08`。

| 项目 | 前 | 后 |
| --- | ---: | ---: |
| 未折叠尾部工具回执 | 170 | 170 |
| 已提交正文完整保留 | 166 | 170 |
| 整段发射估参token | 303335 | 312127 |
| 同一冻结头估参token | 4306 | 4306 |

4条实际损失：源#2007（Read交接提示词文档）、#2044/#2124/#2147（Bash）；原文字符8668/8469/17280/9667，原投影各只剩5189字符。修复后不需要重新取回即可保留其已提交正文。

六项接受项全部通过：同头、头文件字节不变、已发布冷视图字节不变、全部170正文保留、源字节不变、不从历史人话建立goal PIN。report/emission/head/cold在 `_wsc_out/unfolded-source-2026-10-08/`。增加8792估参token来自恢复未折叠回执，不是卡面/历史用户原话扩大。不是厂商token或实际费用。

## 完成边界

本批证明的是“KEEP历史层二次缩短已提交回执”的结构修复，不能据170/170判定模型利用了全部有效信息。原执行层预算已经截断的内容不会被伪造回来，仍靠其完整spill/来源实际召回；其他Bash去噪、等价结果fold等路径要继续审计。

默认旁路关闭；未改真实旧会话、旧冻结头或冷对象。T14e仍保留未勾（剩余输出路径审计），T10/T13/T14f真实模型长任务/有用信息/费用验收未完成。后续按总账固定方向：组合任务状态与时机策略，真实源多时点及实际模型A/B；不把回执字节完整等价为不漂移。
