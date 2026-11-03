# 泛化验证：4 种形态任务 × 2 臂

2026-11-04 03:30–05:10。新增 4 个不同形态的 fixture，各配隐藏测试，两臂各跑一次。
所有产物在 `experiments/runs/gen-*`、`experiments/runs/gen2-*`、`experiments/report/raw/`。

## 任务与基线（未修改时的分数）

| 任务 | 形态 | 基线 | 隐藏测试 |
|---|---|---|---|
| bugfix | 修 5 个 slug 缺陷（分隔符折叠/首尾裁剪/音译/符号/空串） | 1/7 = 0.143 | `hidden/slugify.test.mjs` |
| feature | 给 CSV CLI 加 `--delimiter`、`--no-header` | 2/6 = 0.333 | `hidden/csv-feature.test.mjs` |
| refactor | 重命名模块与函数、不留兼容层 | 2/5 = 0.400 | `hidden/refactor.test.mjs` |
| config | 配置格式 v1→v2 迁移，双格式共存 | 1/7 = 0.143 | `hidden/migration.test.mjs` |

## A 组：生产预算（WSC capacity 28235 / 原生 0.366×65536）

| 任务 | WSC 分数 | 原生分数 | WSC 请求/输入/墙钟 | 原生 请求/输入/墙钟 |
|---|---|---|---|---|
| bugfix | 1.000 | 1.000 | 12 / 16.0k / 54s | 10 / 14.4k / 60s |
| feature | 1.000 | 1.000 | 13 / 30.3k / 65s | 18 / 57.3k / 125s |
| refactor | 1.000 | 1.000 | 12 / 15.7k / 36s | 11 / 15.4k / 35s |
| config | 1.000 | 1.000 | 11 / 15.6k / 44s | 12 / 33.8k / 83s |

**但这组没有压缩发生**：4 个任务都在 16–57k token 内完成，低于 28k 容量下的触发点，
WSC 引擎根本没被调用。所以这组只证明"开启 WSC 不影响小任务"，不构成压缩效果证据。
输入 token 的差异是噪声，不是 WSC 的功劳。

## B 组：强制高频压缩（WSC capacity 6000 / 原生 0.0778×65536，retain 都压到 816）

| 任务 | WSC | 原生 |
|---|---|---|
| bugfix | **超时 900s**，7/7 | 284s，1.000 |
| feature | **超时 900s**，6/6 | 181s，1.000 |
| refactor | **超时 900s**，5/5 | 174s，1.000 |
| config | **超时 900s**，7/7 | 201s，1.000 |

压缩次数与步数：

| 任务 | WSC 压缩/步 | 原生 压缩/步 |
|---|---|---|
| bugfix | 25 / 26 | 19 / 15 |
| feature | 29 / 30 | 12 / 10 |
| refactor | 31 / 32 | 16 / 12 |
| config | 25 / 26 | 16 / 12 |

## 结论

1. **质量泛化成立**：4 种形态、两臂共 8 次运行全部满分，WSC 没有在任何形态上引入回归。
   这组任务本身偏简单（基线 0.14–0.40，模型都能修完），属于天花板效应，
   只能证明"不退化"，不能证明"更强"。
2. **成本优势有边界**：生产预算下 WSC 不劣于原生（feature/config 输入减半）；
   但预算压到 6k 时，WSC 几乎每步压缩一次（25–31 次），每次都多一个选材请求，
   四次运行全部在 900s 上限内没跑完，而原生 174–284s 全部完成。
3. **失败模式是"不收敛"不是"做错"**：四次超时的 WSC 运行补跑隐藏测试全部满分，
   说明任务早已做完，是压缩开销+压缩后状态丢失导致它停不下来。
   这和 L 臂（12 文件工作集）观察到的现象一致。
4. 因此：**WSC 的优势条件是压缩次数少**（大预算、长任务），
   与 `DIRECTION-1-2-FINDINGS.md` 里"小预算买不到东西"的结论一致。
   生产配置 28235 正好在有效区间，维持不变。

## 复现

    pwsh -File experiments/tools/run-matrix.ps1                       # A 组
    pwsh -File experiments/tools/run-matrix.ps1 -WscProfile ab-echo-s -NativeProfile ab-native-s -Prefix gen2   # B 组
