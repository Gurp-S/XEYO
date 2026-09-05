# XEYO 评估方案

---

## 一、起步阶段（快速验证核心能力）

| 基准 | 评测维度 | 使用方法 | 预估 Token / 成本（人民币） |
| :--- | :--- | :--- | :--- |
| **BFCL** | 工具调用（函数调用） | `pip install bfcl-eval`，运行 `bfcl generate --model MODEL_NAME --test-category simple_python,parallel` | 输入 ~40K + 输出 ~10K <br> **≈ 0.004 + 0.045 = 0.049 元** |
| **HumanEval** | 代码生成（Python） | `pip install human-eval`，运行 `evaluate_functional_correctness sample.jsonl` | 输入 ~60K + 输出 ~20K <br> **≈ 0.006 + 0.09 = 0.096 元** |
| **MBPP** | 代码生成（Python） | 从 Hugging Face 加载 `google-research-datasets/mbpp` | 输入 ~100K + 输出 ~50K <br> **≈ 0.01 + 0.225 = 0.235 元** |
| **MMAU** | 综合（离线多任务） | 直接加载数据集，无需联网调用 API | **0 元（纯本地计算）** |

> **起步成本合计**：约 **0.38 元**（若只选 BFCL+HumanEval 则不足 0.15 元）。


## 二、进阶阶段（贴近真实场景，含 SWE 系列）

| 基准 | 评测维度 | 使用方法 | 预估 Token / 成本（人民币） |
| :--- | :--- | :--- | :--- |
| **ToolBench** | 大规模工具调用（16k+ API） | 克隆仓库，配置 API 密钥，运行评测脚本 | 输入 ~250K + 输出 ~100K <br> **≈ 0.025 + 0.45 = 0.475 元** |
| **τ‑Bench** | 工具调用（零售/航空领域，含可靠性指标） | `pip install tau-bench`，配置领域与模型 | 输入 ~70K + 输出 ~30K <br> **≈ 0.007 + 0.135 = 0.142 元** |
| **Terminal‑Bench 2.0** | 端到端终端任务（DevOps/科学计算等） | Docker 沙盒，运行 152 个任务（可限制数量） | 单任务：输入 100K + 输出 50K → **0.235 元** <br> 完整 152 任务：**≈ 35.7 元**（可只跑 10 个任务 → **2.35 元**） |
| **LoCoMo‑Refined** | 长期记忆（**更严苛的评测标准**） | 从 GitHub 仓库 `mem-eval-suite/LoCoMo_refined` 获取代码和数据集 | 参考 LoCoMo 成本：**输入 ~800K + 输出 ~400K → 1.88 元**<br>（LoCoMo‑Refined 本身不产生额外 API 调用，成本来自被测 Agent 的推理消耗） |
| **SWE-bench Lite** | 代码修复（**300 实例**，11 个热门 Python 仓库，过滤为单文件修复） | `pip install swebench`；`python -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench_Lite --predictions_path <path>`；**需要 Docker** | **单实例**：输入 ~200K + 输出 ~100K → **0.47 元**<br>**完整 300 实例**：**≈ 141 元**（$20） |

> **进阶小规模建议**：Terminal(10) + ToolBench + τ‑Bench + LoCoMo‑Refined + SWE-bench Lite(10实例) ≈ **2.35 + 0.475 + 0.142 + 1.88 + 4.7 = 9.55 元**。进阶完整（Terminal 全量 + SWE Lite 全量）≈ **35.7 + 141 = 176.7 元**。


## 三、专项阶段（深度评测特定能力，含 SWE 高阶版）

| 基准 | 评测维度 | 使用方法 | 预估 Token / 成本（人民币） |
| :--- | :--- | :--- | :--- |
| **ComplexFuncBench** | 复杂函数调用（多步/约束推理） | 加载 5 类挑战场景数据集 | 输入 ~140K + 输出 ~60K <br> **≈ 0.014 + 0.27 = 0.284 元** |
| **MCP‑AgentBench** | 基于 MCP 协议的工具调用 | 600 个查询，6 个复杂度 | 输入 ~250K + 输出 ~100K <br> **≈ 0.025 + 0.45 = 0.475 元** |
| **MultiPL‑E** | 多语言代码生成（18 种语言） | 扩展 HumanEval 至多语言 | 输入 ~1M + 输出 ~0.4M <br> **≈ 0.1 + 1.8 = 1.9 元** |
| **LongMemEval** | 深度长期记忆（5 大能力） | 需配置 Embedding 和评判模型 | 输入 ~1.4M + 输出 ~0.6M <br> **≈ 0.14 + 2.7 = 2.84 元** |
| **GAIA** | 综合通用 AI 助手（需多步推理/工具） | 需 Docker，运行 `evalscope` 加载 GAIA 数据集 | 输入 ~2M + 输出 ~1M <br> **≈ 0.2 + 4.5 = 4.7 元** |
| **SWE-bench Verified** | 代码修复（**500 实例**，人工验证可解，OpenAI 主导筛选） | `pip install swebench`；`python -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench_Verified --predictions_path <path>`；**每实例超时 1800 秒** | **单实例**：输入 ~200K + 输出 ~100K → **0.47 元**<br>**完整 500 实例**：**≈ 235 元**（$34） |
| **SWE-bench Pro** | 代码修复（**731 实例**，多语言：Python/JS/Go/TS，长周期任务，抗污染） | `from datasets import load_dataset; load_dataset('ScaleAI/SWE-bench_Pro')`；**需 Modal + Docker**；建议先 `--limit 5` 冒烟，再 `--limit 25` 小规模 | **单实例**：输入 ~300K + 输出 ~150K → **0.705 元**<br>**完整 731 实例**：**≈ 515 元**（$74） |
| **SWE-Compass** | 统一编码能力评估（**~2000 实例**，8 大任务类型 × 8 大场景 × 10 种编程语言） | `bash scripts/setup_env.sh`；`python scripts/run_instance.py --data data/test.jsonl --instance_id compass_01234`；`python scripts/eval_aggregate.py` | 视任务复杂度而定，**完整 ~2000 实例**：输入 ~400M + 输出 ~200M → **≈ 940 元**（$135） |
| **SWE-bench (Full)** | 代码修复（**2,294 实例**，混合难度，含 ~8-12% 不可解/有歧义样本） | `python -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench --predictions_path <path>`；**不推荐**，建议用 Verified 替代 | **完整 2,294 实例**：**≈ 1,078 元**（$155） |

> **专项全量合计**（不含 SWE Full）：约 **0.284+0.475+1.9+2.84+4.7+235+515+940 = 1,700 元**。建议按需选择：

| 推荐场景 | 推荐基准 | 预估成本 |
| :--- | :--- | :--- |
| 快速验证代码修复能力 | SWE-bench Lite（10 实例） | **4.7 元** |
| 标准模型对比（业界共识） | SWE-bench Verified（完整） | **235 元** |
| 前沿能力挑战（多语言/长周期） | SWE-bench Pro（完整） | **515 元** |
| 全面能力画像 | SWE-Compass（完整） | **940 元** |


## 四、持续追踪阶段（动态监控与对比）

| 追踪工具 | 评测维度 | 使用方法 | 预估成本（人民币） |
| :--- | :--- | :--- | :--- |
| **AgentBench (npm)** | 综合 10 个交互任务（含编码、网页等） | `npx agentbench`（需 Docker） | **< 0.1 元/次**（约 2 分钟） |
| **BFCL Leaderboard** | 函数调用实时排名 | 提交结果到 Berkeley 官方榜单 | **< 0.1 元/次**（仅测试成本） |
| **xbench（红杉中国）** | 长青动态综合评估 | 使用评判模型自动打分 | **1～5 元/次**（视任务量） |
| **LiveBench** | 编码任务动态排行榜（月更） | 运行最新题库 | **1～3 元/次** |
| **SWE-bench Leaderboard** | 代码修复实时排名（提交到官方榜单） | 提交预测结果到 [swebench.com](https://www.swebench.com) 官方榜单 | 取决于提交的实例数量（按 Verified 完整 500 实例约 **235 元**） |

> **持续追踪月成本**（每周跑 4 次 AgentBench + 1 次 xbench + 1 次 SWE Lite 小规模）≈ **1～10 元/月**（不含完整 SWE 提交）。

---

## 五、检索观测口径（⑱，Cursor 在线 A/B 对等；先定口径，不埋码）

> 依据：`docs/实施计划/46-cursor博客技术融合优化计划.md` §⑱ + `docs/实施计划/48-cursor博客技术融合·第二批规划.md` §2。
> 对齐 Cursor《Improving agent with semantic search》的在线 A/B：无语义搜索时**不满意用户请求 +2.2%**、
> 语义搜索使**代码保留率 +0.3%（≥1000 文件 +2.6%）**。XEYO 有 `usage/audit` 可埋点，但需先有
> 「采用 / 后续追问」标注。**本节约定口径，暂不改代码。**

### 5.1 要观测的指标
| 指标 | 定义 | 埋点来源 |
| :--- | :--- | :--- |
| **代码保留率** | 本轮模型产出代码里被保留（未在下轮被反向/重写）的占比 | 后续 turn 对前轮 code 区域做 diff（保留 vs 覆盖） |
| **不满意请求率** | 用户在下轮发起「后续追问 / 纠正 / 反向」的频次 | 用户消息语义（定位为纠正/追问类） |
| **检索采用率** | 检索命中里被 agent 实际采用/打开的比例 | `memory.search` 命中 → `touch_last_used` 已标记；/ `observe` 轨迹 |

### 5.2 埋点前提（先达成，再开算，不全量）
- 需要先有「采用 / 后续追问」**标注**（现有 `observe.py`/`session_md`/`rollout_summaries` 是候选数据源，
  但尚无判定「追问/纠正」的语义标注）。
- 建议先**小样本人工标注**一份「是否不满意请求」金标，验证自动判定准确率后再扩到全量。

### 5.3 观测口径约定
- 语义搜索（⑯）尚未启动前，先以「词法检索」为基线（见 ⑰ `python/evals/retrieval_bench.py` 的
  `hit@k`），记录 `baseline` 值；将来⑯上线后在同一下基准上跑 `hit@k` 对比（对齐 Cursor +12.5% 口径）。
- 只统计「≥1000 文件」仓库与「小仓库」两档，分别报告（对齐 Cursor 分档）。

### 5.4 本轮动作
- 只定口径（本节约定），**不改代码**；⑯ embedding 层未启动前不埋在线 A/B。


## 💰 总成本对比（含 SWE 系列）

| 评测范围 | 推荐组合 | 总成本（人民币） | 备注 |
| :--- | :--- | :--- | :--- |
| **起步** | BFCL + HumanEval + MBPP（可选） | **0.15～0.38 元** | 验证基础能力 |
| **进阶（小规模）** | Terminal(10) + ToolBench + τ‑Bench + LoCoMo‑Refined + SWE Lite(10) | **≈ 9.55 元** | 快速验证真实场景 |
| **进阶（完整）** | 同上（Terminal 全量 + SWE Lite 全量） | **≈ 176.7 元** | 全面评估 |
| **专项（按需）** | SWE Verified（完整） | **≈ 235 元** | 业界标准对比 |
| **专项（按需）** | SWE Pro（完整） | **≈ 515 元** | 多语言/长周期挑战 |
| **专项（按需）** | SWE-Compass（完整） | **≈ 940 元** | 全面能力画像 |
| **持续追踪（月）** | 每周运行 4 次 AgentBench + 1 次 xbench | **< 10 元/月** | 持续集成监控 |
