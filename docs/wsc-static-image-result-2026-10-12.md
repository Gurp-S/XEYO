# 批次95：工具结果的表示由类型决定（仅静态）

结构性根因：Anthropic._tool_result_content以len(inner)>1选择数组或字符串。空文字+单张有效图片时inner只有一个image，转换却返回空字符串，丢失有效负载。文本长度/内容块数量不能决定媒体可否降为文本。

修正既有转换函数：有有效image就保留结构化数组；纯文本仍是字符串。沿原_blocks_to_anthropic把相邻image_url折进对应tool_result，调用ID及错误标志不变。无新提示、组件或存储格式。实际请求与context_input共用该编码链；这不证明媒体token估参精确。

静态阅读构造tool_result_message、兄弟图片归属、转换/合并路径。既有test_tool_result_with_images_becomes_block_array只覆盖非空文字+图片，不能证明空文字+单图片修复通过；本批没有修改或运行测试。修改python/model/anthropic.py，测试0、编译0、API0、费用0，无部署/真实源修改。

范围：正常原生媒体结果的单图丢失。迟到结果候选仍拒绝媒体并默认关闭；混合/迟到媒体完整续接、真实模型效果和容量精确性尚未验收，T18/T14d及其他两块最终效果继续开放。
