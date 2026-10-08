# 批次45：真实强压覆盖审计与授权的交接协议

## 用户决定（本批已明确授权）

用户对强压无状态边界选择：**允许模型先生成结构化交接，再确定性压缩**。该授权允许增加专用交接生成调用；没有授权改变普通压缩模型自决、确定性WSC、80%事实通知、85%起点或改写旧冻结前缀。引擎不以历史词句自行派生目标，交接内容是模型声明，执行真值仍由真实工具回执证明。

这是已确认的后续方案，不再重复请求同一授权。相比保留未被状态覆盖的所有原文，该方案避免重新把全部历史用户原文推回热头。

## 真实生产强压入口反控

新增可重复离线评测 `python/evals/wsc_uncommitted_force.py`。相同隔离付款规范、已执行工具和历史负载，按native/回退×有/无初始检查点四臂实际调用`force_compact`。不是手工设游标后调用投影；没有API调用。

证据：`_wsc_out/uncommitted-force-2026-10-08-a/report.json`及各臂`emitted.json`。

- 四臂游标均实际越过规范来源，源消息完全不改。
- 无检查点两臂：交接、完整规范、报告verification_call_id约束均未进入热层。
- 有检查点两臂：三项均进入热层。
- 四臂通过真实FileReadTool读已发布来源，4/4恢复完整规范。

这证明结构缺口是未声明工作状态未被投影覆盖，而不是存档不完整。批次43模型反例已证明此缺口可造成漏做；本批机制证据不单独充当模型行为结案。

## 工具描述纠正

`python/tools/compact_description.py` 撤销无条件保证保住目标/步骤的承诺。当前完整英文：

```
Requests deterministic compaction before the next call. Task facts come from successful TodoWrite declarations: goal, steps, decisions and linked evidence. Unread results remain intact; historical sources have exact Read references. Undeclared task state is unavailable. Acceptance is pending execution. No arguments.
```

它陈述已实现能力及边界，没有建议或执行导演。未来交接生成主路径真正接通后，描述必须按真实最终能力再更新。

## 新协议校验模块

`python/memory/wsc_handoff_validation.py`：模型输出使用已有TodoWrite完整状态结构，禁止merge；显式稳定步骤ID且唯一；活跃状态必须有objective与规范来源；引用的规范ID在输入内唯一，验收调用/回执必须唯一且按正确顺序存在，未完成或取消回执不能作为完成的验收来源。失败回执可以引用，不改成成功。

校验只证明结构与来源，不能证明模型声明在语义上完整或正确。校验函数不执行工具、不写状态、不发请求、不推进游标，因此坏输出不会提前改变已冻结前缀。拒绝不存在/重复来源、缺ID、部分更新和缺检查点。原TodoWrite解析器可能自动补ID，所以本协议检查的是模型原始提交ID，不能用自动生成ID掩盖模型漏声明。

`python/tests/wsc/test_handoff_validation.py`11条；联合主时机及模型请求18 passed。此前描述纠正后7 passed属同集合，不相加。本批API费用0。

## 实施剩余

**尚未接入主query_loop生成/提交/强压事务**。下轮固定完成：在容量强压前用当次完整未折叠输入生成结构化状态，严格校验后通过真实TodoWrite执行与调用回执追加提交；提交成功才基于新源折叠，再重测完整请求。生成错误、取消、坏来源或提交失败均不能静默吞掉未覆盖任务信息；请求费用/输出上限、事件计量、重试与落盘恢复需一起验证。不能把本模块已通过误报为无检查点漏做已修。

T16保持未勾；普通Compact生成是否沿用该协议应以主链集成证据决定，不预先声称已经修改。
