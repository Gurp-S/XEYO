# WSC 图片传输体积与输入占用分离（批次128）

## 结构性问题与合同

127未支持媒体时降级为完整编码输入的UTF-8/4，图片base64也进入字节计数。相同像素可因PNG压缩方式改变数十倍体积，却不改变图像token；因此这是传输表示与模型输入表示混淆，不能靠去掉某张图片、按样本拟合倍率或缩小所有图片解决。

[官方Vision说明](https://api-docs.deepseek.com/guides/vision/)按尺寸处理图像，当前Flash每张上限1024token，多图逐张独立。新model/deepseek_media_count.py只核验已支持的文本/图片输入信封；现有固定V4.1编码器按原顺序将图片转为占位并返回图片记录，deepseek_count对文本作参考计数、每图加1024上界。basis明确为deepseek_v41_text_reference_with_image_upper_estimate，不是精确尺寸计数或厂商回执。

没有解码图片、下载外部图片、重编码实际输入或改写历史。图片只在实际编码后的user图像块计数；未物化引用、未知内容块/型号/网关及不支持的输入仍降级，base64作为普通工具参数文本时不冒充图像。纯文本及文本块数组保持文本参考口径。复用127的两客户端/CountedInput入口，无新增开关。

## 真实API体积对照

新增evals/wsc_image_transport_behavior.py生成200×200的137数字图片，同像素分别PNG压缩等级9/0，校验解码像素SHA256相同；原图及请求都保存。两份image_bytes=3044/120295，旧当前输入字节估参1064/40148，新上界估参两份均1041。

官方Flash两次请求实际prompt_tokens均200、输出均6、hit均0，均准确输出number=137。两份请求没有WSC折叠，这是传输表示的独立计量对照，不是压后任务续接证明。压缩等级只是实验变量，产品不改变图片编码。

证据_wsc_out/media-count-2026-10-12-128/api/{compressed,uncompressed}保存fixture.png、request.json、response.json和report.json；review为未付费预审请求。无重试、max_tokens64、官方api.deepseek.com；现有峰时人民币口径费用合计估算0.000896元，不是扣款账单。发送前字节预算仍按完整实际请求准入，未为实验放宽0.5元/调用及0.4元/轮限制。

1041明显高于实际200；上界消除压缩体积敏感性，却不解决多张小图上界过保守的问题，不能因此称80/85精准。官方尺寸计算与实际usage仍是后续计量方向，禁止把此次200减成全图常数。

## 回归与改动

新增python/model/deepseek_media_count.py、tests/wsc/test_deepseek_image_count.py及evals/wsc_image_transport_behavior.py；修改deepseek_count.py及test_deepseek_reference_count.py的旧“媒体全不支持”合同。没有改官方参考资产或模型可见文本。

三模块最终29项通过：image_count、reference_count、provider_counted_timing。含真实有效PNG30张的请求准备链：旧字节估参超过1048576窗口的85%，新图像上界计量小于32000、自动fold次数0、来源不变。此例为离线准入回归，未向模型发送30张图，不声称真实1M容量压力验收。

最初3失败25通过暴露我误把官方返回的media_data字典当图片列表计数，造成无图也加1024、多图漏计；核对底层返回契约后按media_data['images']处理，最终29通过。未放宽断言或覆盖旧失败证据。无部署/重启/全局安装、旧冻结/冷对象不改。

## Goal边界

已处理官方Flash支持图像的传输字节引起虚假高占用这一结构性根因，主源码共享入口采用明确图像上界。T14d精准尺寸/未知媒体/其他厂商计数仍开放；T16复杂长任务、T18默认迟到续接及媒体使用、T13/H22/T11一般收益/迁移仍保持完整范围，Goal不完成。
