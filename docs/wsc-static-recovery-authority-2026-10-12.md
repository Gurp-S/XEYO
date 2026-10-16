# 批次90：恢复失败不等于空历史（仅静态）

用户要求只静态审查。本批没有运行代码测试、编译、API、真实重放或部署。

## 结构性根因

messages_from_transcript把OSError转为空列表，load_session_messages把所有异常转为空列表。SessionPool冷建收到空历史可能使用客户端替代或创建空engine；回溯同步则会用空列表replace_history。读取失败因此被当作“确实无历史”的权威事实。

此外，大消息content_ref恢复时文件缺失/读取失败/解码失败/JSON失败均生成空content，执行侧可把缺失工具正文当作正常空结果。已有content_hash未在这条恢复路径核对。

## 不变量与实现

恢复必须先取得来源再替换执行状态；无法读取不等于来源不存在或正文为空。复用现有读取/异常机制：

- load_transcript直接打开文件，仅FileNotFoundError返回空列表；权限、目录及其他读失败传播，不先用is_file把非文件错误当空。
- messages_from_transcript与load_session_messages去掉异常转空。正常新会话无文件、空sid或关闭持久化仍沿现有空历史路径。
- 既有blob解析器增加strict参数，默认保持展示容错；messages_from_transcript执行恢复启用strict，实际读取正文，校验已有sha256并解析JSON。缺失/损坏/摘要不符均停止执行恢复；旧行未保存摘要时只读解析，不猜摘要。
- 静态确认SessionPool冷建先读取后发布engine，回溯同步先读取后replace_history，异常路径不清空旧store；CLI同样在创建engine之前恢复。

不增加状态机、文件格式、模型指导文本或迁移组件。未修改既有源文件、冻结头或冷对象。

## 边界与后续

运行效果未验证。JSONL坏行跳过、归档缺失发现、blob写入耐久性、展示/状态读取的容错边界仍需审查。不存在的旧文件和本来无文件尚无独立完整性清单区分，本批不能证明全来源恢复。批次89的多代轮转测试仍描述淘汰旧行的旧合同；用户禁止代码测试，本批没有改测试或宣称它通过，留待允许验收时迁移。

改动：python/session/record_transcript.py、hydrate.py、transcript_blobs.py。仅静态核对调用接口及发布顺序；测试0、编译0、API0、费用0。四块最终效果仍未结案。

## Goal恢复记录

本轮用户明确要求恢复goal，已通过create_goal恢复原完整目标为active，延续总账范围和四块验收，未把此前进度清零或缩减目标。新goal使用计数从本轮重新开始；旧计数不等于当前记录计数。
