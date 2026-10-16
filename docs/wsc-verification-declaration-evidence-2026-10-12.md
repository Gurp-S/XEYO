# WSC 显式验收身份声明保全（批次130）

## 根因与修复

129模型两组多列TodoWrite提交ID。核对原始291声明、292成功回执及活跃投影，显式verification_call_ids确实5项，已有verification_receipts也只有5项，并不是collect自动混入提交ID。模型自行扩展回答；不能据此过滤TodoWrite或将工具名等同于证据角色。

进一步发现活跃状态丢掉了声明本身的verification_call_ids列表，只显示解析后的执行回执和未知来源。声明的绑定集合与可解析的执行事实不等价：缺失/模糊身份也属于声明，提交/其他执行则不能因展示而自动并入。结构规则是原声明字段无损保留，解析结果另列，不重推声明。

改python/synaptic/task_checkpoint.py复制原verification_call_ids；task_handoff.py显示“验收调用身份（声明）”原列表。没有建议、许可指令、工具名过滤、自动增删身份或验收结论变化。新字段进入新建投影；不改已发布头/冷对象。

新增tests/wsc/test_verification_declaration_projection.py：当前提交ID不自动加入、失败结果保留失败、未知ID仍在声明且标未知、明确绑定的先前TodoWrite仍可作为证据。联合task_continuity、terminal_verification共36项通过，原输入不变。

## 真实同源对照

沿129相同来源/问题/绑定开关与两fold/恢复入口重建新副本。native游标283→287、追加旧头及完整重启相同；头19531→19720字符。新增189字符及派生内容寻址引用变化，不是回热原文。

129模型返回6ID含当前提交，130返回原声明5ID严格相等；当前phase及7待办也准确。state-acceptance.json独立对照原声明/成功回执，不用投影自身充当oracle。这是单次同源对照改善，不是所有模型保证。

冷召回仍失败：130模型0Read，两个原文字段空值；本地真实Read依旧2/2精确可取，初始输入不含这两条原文。因此本批没有关闭T13，也没有通过提示导演来补弱模型行动。

证据_wsc_out/real-verification-field-2026-10-12-130/phase：input.json、report.json、state-acceptance.json、cold-receipt-audit.json。1次官方Flash API，现有计价口径估算0.0291772元，非扣款账单；每次≤0.5元、整轮≤0.4元、无重试。源码字段保全已接入；没有部署/重启或候选默认推广。

## 旧代恢复核对

复制129已保存头/working数据，使用同一规范来源链，在新环境恢复旧代，保持其原cwd/来源身份。当前代码无新fold：head_equal=true、cursor287→287、旧离线目录所有既有文件字节保持，16文件→16文件、API0。见_wsc_out/old-head-recovery-2026-10-12-130-corrected/migration-audit.json。这证明这一旧代/来源的冻结兼容，非所有升级场景。

首次辅助脚本直接解析JSON行却漏掉surface/blob解析，不是生产规范来源，错误地产生head_equal=false与一个新冷副本；未覆盖既有旧文件。旧错误报告留在同名130目录，不能作为生产回归结论。纠正为resolve_transcript_rows(fold_surface_rows(load_transcript(...)))后旧头完全保持，不以放宽seal来刷绿。

## Goal边界

声明ID元数据遗漏已修复，36相关回归及一次真实模型字段对照通过，当前旧代兼容通过。T16复杂执行、T18默认续接及媒体、T14d其他计量、T13/H22/T11自然冷召回/一般收益与迁移仍开放。下一步围绕模型继续执行时是否消费必要来源，以及现有历史来源入口与当前文件入口的身份边界，禁止回到泛关键词清理或全面用户历史回热。
