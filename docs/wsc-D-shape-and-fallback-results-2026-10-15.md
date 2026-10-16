# D：持久身份、声明合同与回退代恢复结果

本轮三项机械修复已接默认源码入口：持久步骤ID碰撞、活跃声明形状/错误续接、fallback代发布与恢复。最终20个相关测试文件 **277/277通过**，免费15项同输入合同对照，新增模型API **0次、0元**。不是全仓通过、现场模型续接或D超过A1的证明。完整Goal仍active。

## 改动与根因

| 默认源码 | 作用 |
|---|---|
| python/memory/wsc_handoff_schema.py | 专用步骤id/content/activeForm非空白；未完成任务的目标/context及相应phase必需；去掉专用ID“自动生成”误导。通用TodoWrite不改。 |
| python/memory/wsc_handoff_validation.py | 原始ID类型/非空保留，唯一性按最终解析后的持久ID；目标/context和ID机械错误增加中性字段事实。 |
| python/memory/wsc_handoff_generation.py | 这两类机械拒绝复用现有原帧回放和原6次额度；不补猜、不重写参数、不HTTP重试。 |
| python/memory/wsc_fallback_publication.py（新） | 显式fallback代复用同一head_store save→load/校验→安装→_emit；不增加存储格式/flag。收益拒绝沿用旧头时，绑定本次显式授权cursor，region_end/头/旧冷对象不变。 |
| python/memory/runtime.py | 实际fallback文本选定后接上述发布入口；非WSC行为保持。 |
| python/memory/wsc_projection.py | 显式无收益且沿用已验证旧头时持久化本代身份；普通请求仍不能发布新代或使用未验证头。 |
| python/memory/wsc_fallback_handoff.py | 新代archive路径使用可解析字面量，Windows分隔符/单引号不破坏publication对象定位；旧发射字节不重写。 |

测试：新增test_handoff_shape_contract.py、test_fallback_publication.py；test_goal_events.py校正已退休的opt-in假设，见下述失败保留说明。所有路径相对仓库根，完整源码快照及SHA在304/sources和result.json。未提交混合工作树，保留用户及其他现有改动；未中断/重启现场XEYO，源码接入不等于现场已重载。

## 同输入前后证据

1. **ID**：原`report`和` report `同时通过Guard，解析后持久ID重复；现在拒绝并给出duplicate_normalized_ids，单个有周边空白的ID仍兼容。不按内容词汇判断身份，不产生另一套ID。
2. **声明形状**：新旧schema由隔离jsonschema4.23.0 Draft2020-12实际验证，同15输入对照；缺目标、空白目标、空context、空白id/content/activeForm六类从schema接受变为拒绝。schema仍不判断自然语言是否真实；同ID不同对象、未知phase等跨字段条件交给Guard。完整责任矩阵见[wsc-D-mechanical-contract-matrix-2026-10-15.md](wsc-D-mechanical-contract-matrix-2026-10-15.md)。测试依赖只在证据目录，不加入产品依赖。
3. **生成恢复**：两个错误类别分别验证原始正文/思考/非法参数未经修改，下一份模型声明再过全部Guard；持续错误、预算拒绝有界；非法第一份不落盘。这里使用受控模型帧，不能当作新的付费模型成功样本。
4. **真正本地事务闭环**：303原失败回归在封存302旧validator下仍失败；首次fallback摘要没有发布记录，下轮源回放。修复后，原断言不降低，真实TodoWrite→持久化→再次fold→flush/hydrate→发射全部通过。304持久重建记录两次cursor **18→20**，region_end仍18，头SHA相同、旧冷对象SHA相同。没有声称第二次吸收了更多历史。这个复现使用构造来源和真实本地执行，不是过去真实私有长会话/现场模型验收。

304/result.json保存完整manifest、源码哈希和结果；303/comparison.json保存schema/Guard对照。冷对象损坏/缺失、源变化、layout/cwd/cursor不符、保存失败均回放完整来源，普通请求没有project/save；新的有引号路径可通过实际Read读取。运行中的Goal五种状态用既有baseline字段，未产生重复状态事件。

## 失败记录与修订

- 303/first.xml：68通过、1失败；303/final.xml：226通过、1失败。是上述既有fallback回归，独立旧validator重跑同样失败，原证据保留。
- 第一次fallback实现修好了代内复用，原回归进一步暴露重启时working cursor20、磁盘head cursor18。重新三轮复审后，将显式无收益分支纳入同一发布合同；没有放宽普通请求的cursor匹配或修改原回归断言。
- 303/fallback-first.xml：27通过、11失败，新增测试夹具忘了在隔离后启用WSC，实际跑了非WSC通道；修正夹具，303/fallback-fixed.xml为38通过。没有据此更改产品默认或把夹具错误称为产品修复。
- 303/goal-baseline.xml：34通过、1失败。旧test_default_off_adds_no_state_fact假设删除退休flag会关闭主路，但当前synaptic.main_policy.enabled恒True，符合用户“收益已证实直接接主路”政策。保存旧测试至303/test_goal_events.before.py，改为验证旧flag缺省不关闭主路、既有前缀不变且只增加一个事实；没有修改生产enabled或Goal事件规则。
- **最终304/final.xml：277通过，0失败。** 不把历次通过数重复相加，不删除失败，不把局部合同当作六轴完成。

三轮评审见shape-contract-three-reviews与fallback-publication-three-reviews两份2026-10-15文档，包括实施反例后的重新三审。最终验证后未再改行为代码。

## 并入、候选与固定TODO

- [x] 上述机械修复已接默认真实源码入口；没有新flag、第二份状态存储、迁移或新增模型调用。冻结头在代内保持字节一致，旧冷对象不覆盖；显式fold只更新获授权的代metadata。
- [x] 完整schema/Guard/持久合同责任矩阵；生成恢复、真实本地commit/恢复/冻结检查，原失败闭环。
- [ ] 控制请求污染objective的语义问题仍未关闭；分载体split候选不借本次修复默认启用，旧294/296/300/302分数不合并重算。
- [ ] U2 epistemic、U3显式transition/fact版本/关系、U4重要状态变化强制原anchor、U5 provenance与entailment完整分责、U6权威runtime phase registry。矩阵不是这些状态协议已经实现的证明。
- [ ] 生产完整renderer薄化、精确Read/媒体完整恢复、安全去噪与UsefulLoss；当前本地冷读合同不替代模型Need→Trigger→Locate→Read→Use。
- [ ] 真正1/3/5/10次模型压缩、重启/迟到/未消费/失效/范围变化/取消/重开/生成失败、跨域独立留出和真实现场重建。
- [ ] 原228质量底线约束18/18、具体值21/21、来源36/36、旧事实复活不增加；同条件A1最终质量验收，最后经济性。仍不能宣布D≥A1、全部治本或Goal完成。

本轮没有付费请求，不重跑已付费前部；上一轮174次/1.54404896元旧费率情景估算仍保留在上一报告，不并入本轮0元，也不删除历史未知费用预留。
