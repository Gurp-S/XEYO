# BenchPress：作为对照基线（零成本收尾）

仓库 `github.com/lil-lab/benchpress`（commit `416ab66c10680964127908d83efe8facbb79aae1`），
论文 *No Mean Feat: Simple, Strong Baselines for Context Compression*（arXiv 2510.20797）。

## 它是什么

10 个 QA 数据集上的上下文压缩评测套件（短上下文 6 个 + LongBench 中长上下文 4 个），
被测对象是**压缩方法**（训练出来的 compressor 或提示式压缩），指标是压缩后回答的
M / EM / F1 / Precision / Recall。

## 预算（未安装，仅从元数据确认）

| 项 | 量 |
|---|---|
| 数据集 | `yairfeldman/benchpress`，46 MB，单个 parquet（`data/train-00000-of-00001.parquet`） |
| Python 依赖 | `datasets>=3.0`、`transformers>=4.40`、`regex`，用 uv 管理 |
| 运行方式 | `benchpress.load()` + `prepare_prompt()` + `evaluate()`，可纯本地跑 |

## 为什么只当对照基线、不接 WSC

和 Compact-Bench 一样，BenchPress 的被测对象是"压缩器"接口：给它 (context, question)，
它产出压缩后的 context，再让 QA 模型回答。WSC 是压缩**引擎**（决定何时压缩、如何选材、
如何组装 checkpoint），不是 (context, question) → context 的函数，没有直接插槽。

所以它的价值是**口径对照**：它的 M/EM/F1 是一套成熟的压缩评测口径，
将来若给 WSC 写适配器，可以借这套指标和数据集，而不必自造。

## 结论

零成本确认完毕：46 MB 数据、三个纯 Python 依赖、可完全离线评测。
接入 WSC 需要适配器，不在本轮范围。
