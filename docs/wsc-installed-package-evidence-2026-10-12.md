# 批次134：安装包遗漏WSC依赖的修复

## 根因与固定规则

pyproject的显式packages.find.include包含memory*，却遗漏它依赖的synaptic*。从源码目录或editable环境运行会隐藏遗漏；独立wheel安装不能找到该包。这直接影响WSC安装交付，不是tokenizer估算或单次模型表现问题。

生产修复只有`python/pyproject.toml`增加`synaptic*`。规则是交付包必须包含WSC运行导入闭包，验收从安装目录导入/运行，而非源码路径；不为本次问题扩展其他打包范围，不改运行策略或冻结数据。

## 构建与安装对照

证据`_wsc_out/package-boundary-2026-10-12-134/{before,after}/report.json`及构建/安装日志。在独立源码拷贝中用满足构建声明的setuptools84.0.0构建，工具链只安装到该证据目录；此前全局65.5.0不满足>=68，没有降低声明或覆盖全局工具链。拷贝按真实include清单和package-data资源选择，before674文件、after747文件，构建前后源文件哈希均保持。

两个wheel都实际pip --no-deps安装到各自独立target。修复前wheel未包含synaptic/__init__.py，安装目录memory.wsc_handoff_scope导入失败No module named synaptic；修复后包含并导入成功。after探针以-B -S运行，禁用site初始化及editable路径；显式使用旧私有tokenizer依赖目录，不安装或修改当前XEYO环境。不是全新机器自动安装依赖或安装器验收。

五个官方计数资源均进入wheel：__init__.py、encoding.py、tokenizer.json、LICENSE、PROVENANCE.json。编码器SHA256=502bdaec8a3fd88ebc24c4721a7038fbe42f2063c664638127056107920035c1，tokenizer=c90dfa01249db1be4245780a052ede752e1361c612ac6d08e2bdada7d599476b，与127固定来源一致；METADATA声明tokenizers<0.23,>=0.22.1。安装目录counter实际返回6/deepseek_v41_text_reference_estimate，无源码资产回退。

## 安装目录实际WSC重建

after/installed-imports.json另核对7个入口均来自独立target：memory.runtime、wsc_projection、wsc_request_timing、session.hydrate、synaptic.task_handoff、model.deepseek、engine.query_loop。这个探针显式附加已有第三方site-packages供httpx等依赖使用，仍禁用site初始化，未把源码根加入路径。

再由安装目录的真实eval入口，对既有293行真实来源执行隔离重建：after/replay/phase/report.json显示两fold283→287、追加旧头保持、恢复请求一致、原转录不变、19720字头、错误为空。当前源码目录不是运行cwd，所有生成对象只落在after/replay。没有调用模型，不能将结构重建称为真实模型续接或冷召回效果成功。

## 数字与边界

2个wheel构建及独立安装、修复前后导入对照、7入口隔离导入、1份真实来源双fold/恢复通过；额外pytest0、API0、模型费用0。wheel是脏工作树的本地验收产物，不是可发布版本，不上传/部署/重启，不修改旧已发冻结头及原冷对象。T14d安装资产边界和T11安装后重建证据推进，但安装器/新机器依赖、真实厂商大容量计数、自然召回与信息收益仍未完成，Goal保持active。
