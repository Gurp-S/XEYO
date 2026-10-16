# 机械 phase 身份旁路：实施前三轮复审

范围只有 AD 原型的 PHASE 引用校验及明确校验结果口径。不是生产 phase registry，不改原生 D/schema/Prompt/提交/冻结头。实际 phase 登记、持久化版本和语义作用域仍在统一清单U6中。

## 第一轮：根因与所有权

根因是 `wsc_ad_candidate.validate_fact` 对非 TASK scope 只要求非空 ID；来源存在或字符串合法无法证明 phase 被登记。已有 `synaptic.task_phase` 可验证原生 phase 列表，不能直接验证 AD 的 scope 形状。否决在 candidate 内新增 phases 然后自行验证引用：候选会成为自己的身份权威。

v1修订：phase IDs、task ID、checkpoint baseline 由调用方的既有封存原生提交快照提供，作为旁路机械预检的外部输入；candidate不能添加phase。读取原生快照时复用原phase校验，不新增另一份持久化 registry 或新提交协调器。

## 第二轮：失败和合法演化

否决全局永久 phase 名称白名单：合法任务可以登记新阶段。旁路只对本次已有外部快照做绑定检查；合法新增 phase 必须由拥有注册权的调用方提供新的已提交快照，不能由 guard 从自然语言推断或自动注册。

外部绑定必须 task 与 baseline 一致；重复/空 phase 身份拒绝；不匹配或不存在phase时返回旧state且不推进checkpoint。正常输入继续经过原 `commit_candidate`，所有原有引用、hash、来源时间和生命周期校验保留。AD1原逐项保留行为也保留；新phase预检失效时整次不发布，并单列该差别，不假称原型提供了原生发布事务。

本次不修改 EXECUTION/FILE_VERSION 校验，不声称独立phase version或完整runtime registry已实现。快照身份可信是调用方边界；纯函数不能认证任意调用方伪造的快照。并发来源密封与实际提交仍由既有原生事务负责。

## 第三轮：收益、公平性和退出条件

否决跑模型重新产生28份候选：当前缺口确定可离线重现，API没有必要。使用旧28探针原样候选的构造方法、原state/来源/相同baseline，在旧guard和旁路上各运行一次；旧报告保持不动。新报告逐项列 checkpoint、原状态保护、错误、整次提交和语义未验证。

另外注册正反例：合法现有phase、外部正式登记的新phase、跨task/旧baseline、候选伪造自有registry、重复/空registry、原hash校验保留及输入不可变。合法语义声明即使语义未验证仍可以机械接受；不能靠拒绝所有变更提高保护率。

验收假设：旧4个不存在phase的变更被拦截，原18机械目标保护不退化，合法机械输入可提交。语义6项仍未验证，不能变成“Guard修好了意图”。零热tokens、零API，仅旁路；合同通过不自动并入D或证明A1质量与任务成功。

三轮完成后仅实施上述预检与离线对照。若外部快照/作用域接口实质改变，重新复审。固定Goal、U2/U3/U4/U5及S1–S9保持，后续实际生成链路和任务验收继续推进。
