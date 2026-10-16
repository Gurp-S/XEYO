# 评测 ArtifactWrite 字节发布缺陷：三轮复审

275实际任务发现：多行模型JSON在Windows上经 `turn_snapshot._atomic_write` 文本模式写入，LF变CRLF；ArtifactSink随后按原UTF8 bytes断言，写成正确产物后工具仍报AssertionError。271紧凑JSON合同未覆盖多行。属于评测入口缺陷，不是WSC压缩或模型任务错误。

第一轮：根因是选择了有平台行尾转换的文本原语来实现“UTF8原字节保存”合同。否决删断言、把失败写入算成功回执或清洗provider内容；修订为旁路ExactArtifactSink，复用已有 `rewind.service._write_atomic` 的binary、fsync、replace，不新增发布事务。

第二轮：否决调用旧call后捕获AssertionError再重写，它会产生两次写入。原ArtifactSink只抽离本次publish钩子，默认仍旧行为；候选在同一验证/记录/receipt路径覆盖钩子，调用一次已有binary原语。范围、大小、类型、尝试记录、原字节断言不变。临时写入/replace失败时旧产物保持、错误上抛，不提供伪成功；任务正确性仍在外部judge。

第三轮：拒绝重新支付275。先重放已付费真实ArtifactWrite参数到两个隔离root，记录旧写成但失败、新原字节成功、实际产物一致及receipt hash。另测LF/CRLF/Unicode/NUL/空内容、错误数据仍能保存并被oracle拒绝、越界/取消尝试、原子replace失败旧文件不变。旧275分数/错误保留，不把离线工具修复重放说成新模型任务成功。

这是评测修复，零API、零生产变化。不启用冷读取default或改模型/任务/source/oracle；它们是独立行为，不能借本次字节修复一并混入。该抽离只服务本次publish钩子，所有新逻辑在新模块。原材料代码身份与新版本分别记录，270不覆盖。
