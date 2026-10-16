# 批次92：首次生产交接的作用域合同（仅静态）

## 根因与正确性

生产query_loop调用handoff_generation时未传scope_protocol，默认False。来源不存在先前阶段或任务范围事实时，第一次活跃交接无需phase_state；已保存的无阶段checkpoint也可能在没有后续消息时被needs_refresh当作足够覆盖。于是后续生命周期校验只能约束已经进入协议的任务，无法防止第一份交接继续混合历史阶段和全任务事实。

不变量：生产压缩的活跃交接从第一次起就明确当前阶段、来源、原文展示选择和每条事实的适用范围；生成、提交和复用判据必须一致。结构化声明是模型给出的事实，规则只校验范围与证据，不从历史关键词推断目标。

## 修正与接线

- query_loop的隔离交接生成启用既有scope_protocol=True，复用已有phase schema和有界拒绝反馈。
- transaction.commit增加兼容的require_phase参数；生产调用True，提交前validate按同一规则复查。未校验的输入不能先写调用或运行TodoWrite。
- needs_refresh识别活跃且无phase_state的旧声明，需追加新的成功声明才能折叠，不重写旧checkpoint/原消息/已发头。
- 空任务或全部完成时沿现有规则不强制活跃阶段。不增加任务状态机、自动语义判定、存储层、模型任务路线或新的费用/水位折叠条件。

此处明确区分首次“无作用域声明”与首次“语义误判”：修正前者的合同，不宣称模型不会把旧事实错误声明成task范围。来源和作用域正确性可以静态校验，语义及后续真实执行仍需最终验收。

## 口径和风险

静态阅读生成schema、validate_phase、事务校验/持久化顺序、query_loop唯一生产接线及needs_refresh。不运行代码测试、编译、API或重放；各项0、费用0，无部署/重启、原会话修改。新增首次协议字段会占用交接输出预算，复杂任务在现有2048输出上限和有界重试内成功与否未验证，失败必须停止折叠。旧测试/离线基线不自动当成新生产接线通过。

修改python/engine/query_loop.py、memory/wsc_handoff_transaction.py、memory/wsc_handoff_scope.py。T16首次声明语义、多fold/恢复实际执行，以及T18/T14d/T13/H22/T11最终效果仍开放。
