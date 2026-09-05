# XEYO 记忆系统完工清单（TODO）

> 目的：把「记忆系统是否完工」从感觉变成可勾选的验收清单。
> 关联：[docs/12-压缩质量验证计划书.md](../%E5%AE%9E%E6%96%BD%E8%AE%A1%E5%88%92/12-%E5%8E%8B%E7%BC%A9%E8%B4%A8%E9%87%8F%E9%AA%8C%E8%AF%81%E8%AE%A1%E5%88%92%E4%B9%A6.md)（表A/B/C/D 已完成部分）、`python/memory/simulator/out/quality_validation.json`（实测数据）。
> 现状：核心机制已实测（append-only 修复后 140 轮尾窗 99.09%、medium 99.32%、真实会话省 24% 成本、新摘要 r=0.917 / session.md r=1.0、回归 129 passed）；C2 默认关、可单开灰度。

## 完工定义

- [ ] **三项实测全绿才宣布完工**：
  1. 真实超长会话（200+ 轮）live 命中率 ≥99%
  2. 超长会话下 `c2_extend_decouple` 打开：命中率不塌（尾窗 ≥98%）且成本再降
  3. 生产连续 3–7 天 `--monitor-daily`：日命中率 ≥95%、C2 触发受控

## 未完成清单

### A. 纯差测试（跑完即有结论）

- [ ] **A1 真实超长会话 live 收敛验证**
  - 命令：`DEEPSEEK_API_KEY=... python python/scripts/memory_stack_eval.py --hitrate-live`（单进程，勿并发）
  - 前提：准备/录制一条 200+ 轮真实会话（含文件重写尖峰）
  - 验收：c2 尾20轮命中率 ≥99%；若只到 ~98.5%，记录提示大小，按 `1 - delta/prompt` 说明何时到 99%
  - 产出：表D 新增 `hitrate_*` 行 + 同步 docs/12 执行状态

- [ ] **A2 `c2_extend_decouple` 打开后的 live 影响**
  - 命令：长会话脚本 + overlay `Params(c2_extend_decouple=True, c2_extend_ratio≈0.1~0.25)`
  - 验收：尾窗命中率不塌（≥98%）、输入 token 再降、扩展确实触发（transition>1）
  - 若命中率塌 → 转 B1 调闸门/扩展逻辑

- [ ] **A3 生产日常监控**
  - 命令：每天 `python python/scripts/memory_stack_eval.py --monitor-daily`
  - 验收：连续 3–7 天日命中率 ≥95%、C2 次数=0（默认关）或受控

### B. 机制/质量问题（测完可能还要改）

- [ ] **B1 压缩态扩展被 θ 门卡死（死代码）**
  - 现状：C2Q 首压后掉到 0.46 < θ=0.5，`decide` 不再返回 C2；扩展不触发 → 超长会话省幅封顶
  - 已落地：`c2_extend_decouple`（默认关）；待 A2 验证后决定是否放宽 `c2_extend_ratio` / 调整经济门
  - 完成标志：扩展在超长会话定期触发、命中率不塌、成本优势可持续

- [ ] **B2 合成源（重工具场景）摘要丢事实**
  - 现状：r_probe `c2_new` synth=0.25、`c2_sess` synth=0.667；A/B 事实层 0/3（r06/r09）
  - 方向：session.md 全覆盖、或摘要混合策略（关键 tool_result 保留片段/结构化）
  - 完成标志：合成源通过率差 ≤5pp 且事实层无 0/3

## 验收记录（每完成一项在此打勾并附证据）

| 项 | 完成日期 | 证据（表D 行 / 数据） | 验收人 |
|---|---|---|---|
| A1 |  |  |  |
| A2 |  |  |  |
| A3 |  |  |  |
| B1 |  |  |  |
| B2 |  |  |  |

## 参考（已达标证据，勿重复测）

| 指标 | 数值 | 出处 |
|---|---|---|
| 超长会话命中率（140轮合成 live） | c2 尾20轮 99.09% | `hitrate_long140_c2` |
| 中对话命中率 | medium 99.32% | `hitrate_medium_c2` |
| 真实会话成本节省（干净口径） | ultra/long 省 ≈24% | `hitrate_clean_*` |
| 新摘要质量 r | real 0.917 / synth 0.25 | `r_probe_c2_new_*` |
| session.md 质量 r | real 1.0 / synth 0.667 | `r_probe_c2_sess_*` |
| θ 扫描 | θ*=0.5、avg_Q=0.568、离线省 32% | `theta_scan_*` |
| 回归测试 | 129 passed | `python -m pytest` |
