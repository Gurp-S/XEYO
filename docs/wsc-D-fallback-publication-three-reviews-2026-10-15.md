# 收益门回退代的发布/复用：三轮复审

## 事故三问

303原有回归在旧302校验器及新校验器都失败，免费trace确定：显式fold首次native收益不足→返回None→runtime发出C2 fallback摘要；下轮普通请求仅查找可验证WSC头，未找到→回放原文。结构根因是两个renderer没有共享发布协议。信息未丢，但已安装的代突然消失、上下文和缓存跳变，违反代内稳定预期。

规则：显式fold选择的fallback头也经过**同一个**wsc_head_store发布、source seal/cwd/cursor/layout/冷对象manifest验证与同一个_emit；普通请求只有复用或完整源回放，不允许临时新建状态。不得只因为working.c2_summary_text非空就复用。旧头/冷文件不改，旧未知状态不自动迁移。

回归：真实收益拒绝样本中旧失败必须通过；冷启动、append、显式下一代、source/layout/cwd/cursor变化、缺失/损坏冷文件、发布失败、只读普通请求不发布、非WSC不变。恢复失败仍回放源，不绕过冷证据检查。只在有对应机械证据后默认接入，无API。

## 第一轮：职责/复杂度

v1想在无WSC缓存时返回None，让runtime沿用working摘要。否决：摘要只有字节/游标，没有完整来源和publication验证；会把失效摘要误用成可信状态，也会破坏既有generation_admission“损坏不新建”合同。

v2复用已有wsc_head_store，不另加fallback存储/schema/flag。只有显式new_generation路径可发布当前已构造好的fallback文本；从同一磁盘记录_restore_frozen校验成功后接入既有_Live/_emit。文本选择仍归原renderer，模块仅负责发布生命周期。

## 第二轮：失败与依赖

否决先把未验证文本放内存，再异步落盘。也否决缺少冷对象manifest时只存text。新生成的archive路径以合法字面量呈现，Windows反斜杠/引号不靠ast猜；旧已发射字节不重写。

v3 save→load/validate→安装→同_emit，任何失败回放全部源。来源seal冻结至fallback_cursor，未消费尾部保持现有protect规则；不在普通请求调用save/project，不擅自提前折叠。未启用WSC或显式关闭相关能力保持原开关边界。恢复中识别普通来源变更时不信任旧working摘要。发布异常只记本地诊断，不给模型增加导演文本。

## 第三轮：公平验收与最小变更

否决为解决短样本让收益门恒通过、修改旧断言、假造一个压缩头。直接运行303原失败函数与独立受控收益拒绝合同；检查真实磁盘manifest、Read冷文件、旧对象字节，以及重启后的同代首条消息完全相同。随后复跑generation_admission的所有损坏/无发布合同和303既有定向范围。

实施仅新增fallback发布模块，runtime在实际fallback文本确定后调用，fallback archive路径在新代使用可解析字面量。保留原本WSC原生发布流程，不重构巨石，不扩大Goal，不将局部冻结协议通过等同真实长任务或D>A1。

## 实施反例后重新三审：显式空收益的代身份

首轮实现已经使旧回归的首个冻结头比较通过，但暴露了下一条重启断言：第二次显式fold收益不足沿用旧头，working游标20而head_store仍18。这是同一发布协议缺口的另一分支，原失败和第一次实现结果都保留，不能仅修第一条断言。

复审1否决普通请求允许任意旧cursor头：会让未授权恢复误跨代。只在显式new_generation且旧头来源已校验的收益拒绝分支，重新绑定当前授权cursor，头字节/region_end/冷视图/lifecycle均保持，不声称吸收了新历史。cursor和region_end职责不同。

复审2否决只更新内存cursor：重启仍坏；也否决不校验save结果。复用同一save→load→安装流程，保存失败回放全部源，不使用未持久的新代。不新建冷对象，不更改之前发给模型的字节。

复审3增加真实两次fold→flush/hydrate对照与前后head/冷文件哈希；运行既有generation_admission损坏样本，普通请求仍无发布。只额外触碰收益拒绝的显式分支，不放宽同源/冷对象/游标检查，不增加语义选择器。两处发布复用同一小函数，不复制第二套状态或序列化。

静态复查补充：runtime snapshot用text，既有lifecycle baseline用goal；直接复制snapshot会错误地产生一次重复状态事件。安装时仅映射原有goal_id/revision/status及对应goal文本，终态空文本沿用既有规则，不携带owner/title等无用字段。五种状态分别验证不新增重复goal事件，既有goal_events合同一并验证，不引入新语义状态判断。
