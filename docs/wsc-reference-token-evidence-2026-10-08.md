# 批次39：官方离线计数与已保存请求回执对照

本批没有新增模型API请求。先核查未提交检查点的路径：`task_checkpoint.project_state`在未观察到成功TodoWrite状态时返回None，完整冷存档不等于已确定当前任务工作集。现有“保住目标/步骤/决定”证明依赖已提交结构状态；强压无检查点的长期任务连续性仍未证明，不能用归档覆盖率冒充它。后续固定方向是模型声明并提交任务工作集/来源/验收绑定，执行层确定性保存，不从历史原话、关键词或首条任务推断活跃状态，也不重新热化全部历史用户原文。

## 计量对照

官方API文档 https://api-docs.deepseek.com/quick_start/token_usage/ 链接V4离线包 https://cdn.deepseek.com/api-docs/deepseek_v4_tokenizer.zip 。包下载1911504字节，tokenizer.json为6367096字节，SHA256=`89085f12ef79460ac5f66d1119325ddfc694b4ab209d80bbd81d35f081dc9614`。

参考消息编码器来自官方 https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash ，固定revision=`60d8d70770c6776ff598c94bb586a859a38244f1`；encoding/encoding_dsv4.py SHA256=`bdbd57c132a1b3725042323d02b98b9d1df28e5f388f134399555d041f5055e0`。已检查该独立实现仅依赖typing/copy/json/re，不执行官方zip中的trust_remote_code演示。

tokenizers 0.22.1仅安装到私有评测目录deps，不改项目/全局依赖。新的`python/evals/wsc_reference_token_probe.py`明确选择本地已检查编码器、tokenizer与历史wire，记录内容摘要；不读取密钥，不联网，不改生产。非文本输入标unsupported，不把图片base64当普通文本token。

对既有9个报告/请求档共21次实际Flash请求复算，21可计数、0不支持；参考值对厂商prompt_tokens最大绝对差33，最大相对差1.1688%。原工具链两个请求：

| 请求 | 旧字节估参 | 官方参考编码计数 | 厂商实际prompt_tokens |
| --- | ---: | ---: | ---: |
| Compact之前 | 3272 | 4764 | 4771 |
| Compact之后 | 2803 | 4253 | 4246 |

全部源/逐请求结果见`_wsc_out/token-counter-probe-2026-10-08/all-comparison.json`。原始付费请求及回执未改。工具schema根据官方参考编码约定挂在首个system消息，再按chat/thinking模式编码；这是本地参考映射，不声称厂商API模板完全同一。

这证明V4文本/工具参考计数显著接近已观察实际值，但仍存在差异；不能直接加33常数便宣称所有长度/模板/型号/媒体均精确。T14d保持未勾，接入前仍需型号/版本与模板适用性、依赖发布、媒体及性能边界。它也不证明长任务模型不漂移。

## 用量与费用口径

已知单价时，每次费用由命中输入量、未命中输入量、输出量分别乘单价即可计算，不需要三次采样。usage只有数量，无法独立反推出单价；有实际扣费额且同币种/同峰谷规则/无其他收费时，三组线性独立用量才可能求解三个价格。累计账单或价格拟合不能替代发送前当前请求容量测量。

本轮新增API费用0元；整体目标及唯一总账的其他未勾项继续开放。
