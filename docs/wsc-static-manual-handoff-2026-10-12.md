# 批次103：手动入口接入同一交接事务（仅静态）

结构性根因：主循环强压已接入结构化交接，但记忆HTTP、slash及chat中的手动compact仍同步直接force。不同入口拥有不同的连续性前置条件，主循环证据不能覆盖这些入口。手动交接也比原同步投影耗时更长，租约不能只有取得/结束而没有续租及身份校验。

共同规则：所有实际产品手动入口先确认执行所有权，再同步确认来源持久化；需要刷新时用当前配置模型提交真实TodoWrite完整交接，沿主循环同一phase/来源/预算/事务校验；成功调用与回执持久化后才确定性force。原文与既有冻结对象不改，新增交接是追加事件。没有合成Compact模型调用，没有另设摘要器或预算。

实施：engine/manual_compaction.py承接共享操作；memory HTTP改异步，slash提供异步dispatcher，commands路由和CLI REPL接异步入口，chat手动分支直接复用同一操作。同步嵌入者只有在没有运行事件循环时可使用同步适配器，已有循环须调用异步接口；实际GUI/TUI HTTP与CLI REPL不走这个拒绝分支。非compact命令保留既有同步执行，HTTP沿既有Starlette线程池机制调度，不改工具清单或斜杠manifest。

准备交接采用已有keep_emission，避免读取投影时受实验/关闭开关影响提前折叠。专用交接请求沿现有PromptAssembler及固定会话日期构造；使用已配置模型，不选择新模型。交接有需要才作为一次新的submit重置原预算，沿配置/env费用上限及原model usage账本计费；回包提供原budget快照，费用未知保持未知。生成每次发送前均复用既有request_conflict检查实际请求序列；未消费结果不会以去噪名义丢弃，放不下仍沿现有硬容量错误停止。

所有权与取消：pool租约续租增加可选lease_id核对及布尔结果，原未传调用兼容。keep_lease仅管理调用者已持有租约的30秒心跳及退出清理，不另建所有权。HTTP/slash取得租约后重取engine；chat复用已取得的租约；两条HTTP路径均检查TurnRunner。操作无await地安装新取消节点并消费已排队stop，后续stop经原engine.interrupt取消。每个交接续轮/来源读取/写入及存盘/fold边界检查原取消和租约；旧持有者不能续租较新租约，结束也沿原lease_id核对。CLI入口按既有REPL串行执行。

应覆盖的回归（按用户当前要求未编写或运行）：三类HTTP/斜杠别名/CLI真实触发及失败回包；一次交接成功提交后折叠、失败不折叠；等待模型期间stop与旧控制器取消后的新操作；超过原租约过期时限的续租、失去租约后禁止写入/折叠；调用落盘成功而工具/回执失败后的重启；交接usage与配置费用上限；旧源及既有冻结字节不变。静态调用检查不是这些回归通过的证明。

限制：未运行任何产品入口/模型/API/代码测试/编译，未部署、未操作真实保存会话。输入容量仍是项目既有估参；未知厂商默认输出预算、复杂媒体、同步大存档阻塞与完整故障恢复仍未被真实验证。旧外部代码若在事件循环里直接调用同步dispatch(compact)，须切到dispatch_async，这不是产品已运行兼容性证明。

本批代码修改：engine/manual_compaction.py、server/session_operation.py、server/session_pool.py、server/routers/memory.py、server/routers/chat.py、server/routers/commands.py、slash/dispatch.py、slash/__init__.py、cli/slash.py、cli/chat_cmd.py、memory/wsc_handoff_prepare.py、memory/wsc_handoff_generation.py。测试0、编译0、API0、费用0。手动交接接线的实现缺口已补；T16/T18/T14d/T13/H22/T11最终真实效果验收仍开放。
