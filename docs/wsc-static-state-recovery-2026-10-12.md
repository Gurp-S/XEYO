# 批次91：历史与任务状态同源恢复（仅静态）

## 合并审查的边界

本批合并检查正文写入、主历史恢复、Todo状态恢复与最终容量准入。仍只静态阅读和修改，不运行代码测试、编译、API或重放。

结构性根因：主历史恢复已严格读取，但surface_rows_for_session用于Todo恢复仍宽容解析blob；Todo恢复和QueryEngine初始化两层吞异常。发生读失败时，消息历史与任务状态可以给出不同结论。旧逐文件回退还无法保证跨归档rollback marker仍支配被影子行。

不变量：任务状态来自同一份合并且回溯处理后的可读来源；恢复失败不得宣称空Todo或绕过合并回溯。正文发布先于引用日志持久化。

## 修正

- surface_rows_for_session先合并fold_surface_rows再strict解析正文，与主消息恢复顺序一致。已被回溯排除的行不再因其缺失blob阻断恢复。
- Todo恢复直接使用上述来源，删除吞错/逐文件回退。task_checkpoint.enabled当前恒为True，没有必要再保留不可达的旧开关回退。
- QueryEngine初始化不再吞Todo恢复异常；只有读取成功后才回填状态并apply_to_tools。
- 关闭持久化时Todo磁盘恢复返回空，与主历史的非磁盘权威边界一致，不读不相关的旧文件。
- write_content_blob在已有临时文件发布前write、flush、fsync，再replace；没有新增存储组件或修改既有消息格式。fsync文件不构成断电后目录项耐久性的全证明。

## 静态核对与限制

surface_rows_for_session的仓库调用方为Todo恢复；load_sidechain_messages当前调用方为展示路由，本批没有盲目把所有展示路径改严格。三provider输出上限及完整请求80/85准入接线已阅读，未知/精确厂商计量没有因此变成已证明。

没有修改模型提示、冻结前缀、既有冷对象或真实会话。修改文件为python/session/transcript_blobs.py、hydrate.py、tools/todo_write_tool/restore.py、engine/query_engine.py。测试0、编译0、API0、费用0，无部署/重启。

仍需验收实际读失败、跨归档回溯、关闭持久化、正文写失败及恢复后任务续接；当前用户禁止运行代码测试，不能把静态顺序当成这些效果已通过。坏JSONL行、旧文件缺失和临时文件并发发布/断电窗口仍需审查。四块最终效果范围保持不变，不宣称全部治本。
