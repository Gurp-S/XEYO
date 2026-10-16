# WSC V4.1 请求参考计数接入（批次127）

## 根因与实现边界

126的实际请求证明完整请求UTF-8/4可能显著偏离实际输入。字符字节不是模型token边界；统一倍率不可能同时覆盖重复英文、中文、工具模板与图片。结构规则是使用与模型匹配的消息模板/tokenizer，计量当前实际编码输入，标清计量来源及误差；无法覆盖时保留明确估算，不拿累计usage或base64字符当精确媒体计数。

旧39批离线探针使用V4，本批没有直接推广它。新官方V4.1资料：[模型文件](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/tree/2cba9e42aa026125f3ed06c6d98c1db82f7ca027)、[参考编码器](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/blob/2cba9e42aa026125f3ed06c6d98c1db82f7ca027/encoding/encoding.py)。固定revision=2cba9e42aa026125f3ed06c6d98c1db82f7ca027；tokenizer SHA256=c90dfa01249db1be4245780a052ede752e1361c612ac6d08e2bdada7d599476b，编码器SHA256=502bdaec8a3fd88ebc24c4721a7038fbe42f2063c664638127056107920035c1。包内保留MIT许可及来源清单，加载核对摘要，不下载/执行trust_remote_code。

先独立离线对照已保存21份历史请求和126三份新回执，再接主链；新生产入口复算同24份输入，最大绝对差46token、最大相对误差0.8555%。126三例原估参误差+47.05%/+27.99%/+4.16%，参考值改为5331/2065/3515对实际5377/2079/3530，误差-0.8555%/-0.6734%/-0.4249%。这证明已观察文本/工具样本的改善，不是零误差计数或所有模型证明。

## 改动与接入

- 新python/model/deepseek_count.py及model/reference_v41/资产包：独立的官方文本/工具模板参考估算，basis=deepseek_v41_text_reference_estimate。
- python/model/deepseek.py接CLI客户端；python/model/openai_compat.py接GUI/TUI服务端使用的DeepSeek兼容客户端，同享叶模块。兼容客户端按实际thinking及reasoning_effort参数计数，不推断其他provider模板。
- python/memory/wsc_counted_input.py复用请求局部缓存；本地参考与免费Anthropic预计数各保留自身basis。通知追加、schema变化、交接/折叠后的输入分别计数，旧输入不能复用；不改last_usage。
- python/pyproject.toml及requirements.txt声明tokenizers>=0.22.1,<0.23，并登记tokenizer/许可/来源包数据。约6.4MB静态资产，不包含权重，不重写官方模板。
- 新python/tests/wsc/test_deepseek_reference_count.py覆盖缓存、完整输入、依赖失败、媒体/来源/型号限制及GUI兼容两种思考模式。

满足已核验官方Flash别名和原生域名的文本/工具请求默认使用此参考值，无新增feature flag。媒体、未知型号、非DeepSeek provider、网关、不支持的模板或缺失/损坏资产/依赖返回None，仍使用原明确UTF-8/4估算，不能声称那些输入已改善。通知文本维持“当前完整请求估算”，没有把参考值称为厂商回执或添加导演文本。

当前官方/models窗口1048576/最大输出393216证据仍来自126，本批不按型号前缀推断或改写用户声明容量。别名可能随厂商演化，固定V4.1资产与适用范围需随版本变更重新核对；本地参考仍存在模板及媒体边界，不等于发送前实际usage。

## 验收与现场边界

三模块最终24项针对性回归通过：test_deepseek_reference_count、test_provider_counted_timing、test_request_timing_loop。此前21项通过后，补GUI主入口及两个思考模式才得到最终24，不能只测CLI就称全入口接入。免费Anthropic计数仍是HTTP模拟合同，不称真实厂商计数验收。

证据目录_wsc_out/token-counter-v41-2026-10-12-127：provenance.json、historical-comparison.json、recent-comparison.json、production-comparison.json。24份原请求/回执字节未改，参考计数首次加载最长约215ms（包含校验/库及tokenizer初始化）；只是这组机器和短请求测量，不是1M性能上界。

本轮模型API0/模型费用0，仅下载固定官方参考资产；回归使用此前私有探针deps，未安装到全局Python、未重启XEYO或部署。依赖声明与源码接入已完成，不能声称当前已启动进程使用了新代码。缺依赖降级已测试；打包登记是源码配置核对，不是发布安装包验收。

## Goal状态

T14d已新增官方Flash文本/工具参考计量的主源码接入与实回执误差证据；无需再停留在字节估参，但不能勾“所有请求准确计量”。媒体、其他模板/厂商、真实Anthropic计数、未知输出余量及实际大容量边界仍开放。T16真实复杂长任务、T18默认迟到续接与媒体、T13/H22/T11一般收益/迁移保持原范围，不以本次计数改善结整个Goal。
