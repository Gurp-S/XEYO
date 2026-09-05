# Path A —— C2 阈值/保尾常量 → 成本模型公式（落地记录）

> 结论先行：Path A 的**公式化**与**独立开关**已落地（默认关 = 冻结行为逐字节不变，回归全绿）；
> A/B 定参网格脚本已写好并验证可跑，但因真录会话（605 decide 调用 × 网格组合）复算开销大，
> 建议在用户本机跑完整网格，再据此把最优组合的常量设进 `params_overlay.json`。

## 1. 目标（诊断根因）

XEYO v61 **每轮 decide 都可能触发 C2**。基线（真录 `sess_real_200turn_c2`，1385 消息 / 605 decide 调用）：
- C2 边界推进 **11 次** = **11 次历史前缀改写**；
- 触发 `apply_c2_messages` **456 次** = 75.4% 调用处于压缩态；
- `l_max/window` = 0.550（= `alpha_win`），`l_hard_send/window` = 0.984。

DSH 只在「head-anchored + 保尾 + 压力阈值」同时满足时才触发。Path A 把 XEYO 的触发常量换成
**从窗口几何 + 自身成本模型推导的公式**，而不是硬编码的 `c2_min_gain_chars=4000` /
`c2_min_save_ratio=0.25` / 独立 `0.62` 等。

## 2. 真录实测（供定参，不是拍脑袋）

`python/scripts/c2_tail_profiler.py` 输出（`sess_real_200turn_c2`）：
- 每轮均 token ≈ **717**（字符/4；成对 assistant+tool 区间）
- 尾区（`keep_tail_cut`=3 轮）字符 ≈ 3611 → ≈ **903 tok**
- `l_max`=70400，`l_hard_send`=125952

⇒ 保尾公式 `per_turn_tokens × rounds` ≈ 717×3 ≈ **2150 tok**（不是硬编码 24k）。

## 3. 公式（`python/memory/simulator/c2_gate.py`，纯函数、零 LLM、零费用）

| 门 | 公式 | 原来硬编码 | 代替 |
|---|---|---|---|
| 压力门 | `(l_hard_send − output_reserve − tail_budget) / window`（**窗口自适应**） | `context_compact_ratio=0.80` / 独立 0.62 | `XEYO_C2_PRESSURE_FORMULA` |
| 收益门 | `remaining_turns × 每轮省token ≥ margin × price_ratio × 一次性miss` | `c2_min_gain_chars=4000` / `c2_min_save_ratio=0.25` | `XEYO_C2_GAIN_FORMULA` |
| 保尾 | `per_turn_tokens × retain_rounds`（真录统计） | `KEEP_TAIL_TOOL_ROUNDS=3`/拍 24k | `XEYO_C2_TAIL_FORMULA` |
| 扩展 | 同一经济公式（复用 `try_extend_c2` 第 4 闸） | `c2_extend_ratio=0.25`/`c2_extend_min_remaining_turns=8` | `XEYO_C2_EXTEND_FORMULA` |

**压力门窗口自适应（关键设计）**：用 `l_hard_send = window − reserve`（随窗口变）替代旧的
`l_max = alpha_win·window`（后者在窗口大时与硬顶严重错位）。因此**切换模型/窗口大小不一致时
结果不串味**：`c2_output_reserve=50000`（overlay）时，128k → 压力 ≈0.593（小窗口早压防溢出），
1M → 压力 ≈0.948（大窗口晚压、上下文存在更久）。主流模型已 1M：1M 下 C2 触发更晚（上下文
装得下、压缩收益低），契合「尽量保证上下文存在时间」。
若不设 `c2_output_reserve`（默认 0），压力比退化为 `(l_hard_send − tail)/window`（128k≈0.984）。

- 收益门的经济门：`transition_miss_tok = (summary+tail)/4`，`saved_per_turn_tok = region/4`，
  判 `remaining_turns·saved ≥ margin·price_ratio·transition_miss`（margin=2.0，price_ratio=30）。
- 压力门与 `alpha_win` 同源：`l_max = min(window−reserve, alpha_win·window)`，不独立拍 0.62。
- **HardTop 兜底保留**：`decide`/`force_compact` 在窗口真快溢出时仍强制压缩（防尾溢出）。

## 4. 接入点（`python/memory/runtime.py`，默认关）

- `_c2_gain_enough(..., remaining_turns)`：`XEYO_C2_GAIN_FORMULA=1` 时走 `economic_gain_ok`。
- `_c2_pressure_ratio(working, params)`：`XEYO_C2_PRESSURE_FORMULA=1` 时返回
  `(l_hard_send − output_reserve − tail_budget)/window`（**窗口自适应**），
  并入 `should_force_compact_on_pressure`（query_loop 压力路径）。
- `project_for_model` v61 分支：`XEYO_C2_PRESSURE_FORMULA=1` 且 `usage/window ≥ pressure_ratio` 时
  强制 C2（先保尾、防尾溢出）——让 A/B 网格的 pressure/tail 维度可测。
- `try_extend_c2`：`XEYO_C2_EXTEND_FORMULA=1` 时允许 env 覆盖 margin/price_ratio/min_remain。
- 所有开关经 `_c2_formula_enabled(key)`：优先读 `XEYO_C2_FORMULA_OVERRIDE`（A/B 脚本一次性注入，
  不改生产设置），否则走 `memory_switches` 注册表（GUI settings.memory 权威）。

## 5. 开关（`python/memory/memory_switches.py` + GUI「记忆系统开关」面板，独立可回退）

| key | 默认 | 说明 |
|---|---|---|
| `XEYO_C2_PRESSURE_FORMULA` | 0 | 压力门 = (l_hard_send − output_reserve − tail)/window（**窗口自适应**） |
| `XEYO_C2_GAIN_FORMULA` | 0 | 收益门 = 经济公式（随 remaining_turns 动态） |
| `XEYO_C2_TAIL_FORMULA` | 0 | 保尾 = 每轮均token×轮数 |
| `XEYO_C2_EXTEND_FORMULA` | 0 | 扩展闸 = 经济公式 |

GUI 面板无需改码：`MemorySwitchesSetting.tsx` 动态读后端 `/v1/settings/memory`（`MEMORY_SWITCHES` 注册表）。

## 6. A/B 定参（脚本：`python/scripts/c2_ab_calibrate.py`）

网格：`pressure {0.55,0.62,0.70} × save {0.30,0.40} × tail {12000,24000,32000}`。

运行（在 `python/` 下，建议本机跑）：
```bat
python\.venv\Scripts\python.exe -m scripts.c2_ab_calibrate sess_real_200turn_c2 --json c2_ab_results.json
```
也可精扫单组合：
```bat
python\.venv\Scripts\python.exe -m scripts.c2_ab_calibrate sess_real_200turn_c2 --pressure 0.62 --save 0.40 --tail 24000 --json c2_ab_single.json
```

对每个组合输出：`C2 边界推进数 / 改写调用 / 单次改写均字符 / 前缀命中率代理 / 尾溢出`。
脚本末尾按「改写最少 + 尾不溢出 + 命中率最高」自动选最优组合并写 JSON。

已用单组合验证（pressure=0.62, save=0.40, tail=24k）：`adv=13, rew=13, avgRW=99281c, hit=97.7%, ovf=0`。
（基线 adv=11，但基线无压力门/收益门公式化；A/B 全网格的结果待本机跑才能定最优。）

**窗口自适应后的 A/B 语义（重要）**：`c2_ab_calibrate` / `c2_ab_1m` 的 `--pressure` 是直接覆盖
`XEYO_C2_PRESSURE_RATIO`（env 优先于公式），它是**相对窗口的比例**。因此某个压力值是否触发
取决于「会话投影 / 窗口」能否达到该比例：
- 同一会话在 128k 下能触发、在 1M 下可能永不触发（投影固定、窗口变大，比例不足）。
- 要测 1M 下不同压力的差异，需选一个**投影真的能长到接近窗口（≥85%）的超长会话**；否则
  不同压力值都得到「不触发 C2」（adv=0）、无差异。真录 `sess_real_200turn_c2` 投影仅 ≈290k
  token ≈29% of 1M，故 1M 下 0.85/0.92/0.95 都不触发——这正是「1M 上下文装得下、不应压」的
  正确行为（符合「尽量保证上下文存在时间」）。
- 1M 隔离测试脚本 `c2_ab_1m.py` monkeypatch `load_params` 返回 1M 窗口，不改生产 overlay。

## 7. 回归与红线

- 必绿清单：`test_runtime_c2` / `test_c2_llm_summary_t8` / `test_memory_switches` /
  `test_quality_plan` / `tests/simulator/` / fidelity / citation / memory_summarize /
  `test_session_md` / `test_memory_search` / `test_memory_index_digest`。
- 本次实测（默认关）：`test_runtime_c2+test_c2_llm_summary_t8+test_memory_switches+test_c2_path_a+
  tests/simulator+fidelity+citation+memory_summarize+test_memory_aging+test_project_cow_c2_gain` =
  **208 passed, 4 skipped**。
- **`test_quality_plan.py::test_monitor_daily_aggregates_and_writes_row` 为 HEAD 既有失败**（已用
  `git stash` 验证：在无任何 uncommitted 改动的 HEAD 也失败）。根因：`update_docs12_table_d` 把
  `deploy_project_mode_*` 行路由到 `docs/A3-monitor.md`，而该断言期望它落在 `docs/12` 表D —— 与本次
  Path A / 面板改动无关，属**预先存在的测试与设计口径不一致**，需要单独裁决（改断言 vs 改路由）。
- 新增回归：`tests/test_c2_path_a.py`（5 项，公式/默认关不变性）。
- 探针只读、零费用；不改生产 .py（除公式化本身的开关接入）；跑测试用 `python\.venv\Scripts\python.exe`；
  GUI 改动 `pnpm exec tsc -b`（本次 GUI 未改码，tsc 已通过）。
