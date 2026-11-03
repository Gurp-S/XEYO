# 下一阶段入口（2026-11-04 收尾）

## 已完成并入库

| 项 | 结论 | 证据 |
|---|---|---|
| WSC vs 原生 | 质量 0.992(n=18) vs 0.786(n=4)；请求 22 vs 70、输入 60k vs 304k、墙钟 126s vs 907s | `QUALITY-VERDICT.md` |
| 主链路并入 | desktop profile 已换 WSC 后端（k2 参数），真机启动 200 | `MERGE-WSC.md` |
| WSM 真实质量 | 62% 重读、工作集覆盖 3%；12 文件可覆盖 85% 但真机 4 倍耗时且不收敛，已拒绝 | `STATUS.md`、`ws-sweep.mjs` |
| 泛化 | 4 形态 × 2 臂 = 8/8 满分；强制高频压缩下 WSC 不收敛、原生 3 分钟完成 | `GEN-REPORT.md` |
| Compact-Bench | 预算实测；production/retention 已跑通；task track 卡 gateway 开关 | `BENCH-COMPACT.md` |
| CompressAgent | 手写最小复现；35% 预算稳定塌到 33%，75% 噪声压过方法差异 | `COMPRESSAGENT-REPRO.md` |
| BenchPress | 46 MB、3 依赖、纯本地；只作口径对照 | `BENCH-BENCHPRESS.md` |
| c 臂分数 | 0.778 / 0.889（9 项 v1） | `report/raw/echo-c-*.score.json` |

## 两个待决策

1. **gateway 开 `WB_ENABLE_ANTHROPIC_MESSAGES=1`**：开了才能跑 Compact-Bench task track。
   警告说会放大额度消耗，属用户决策。
2. **给 WSC 写 bench 适配器**：Compact-Bench / BenchPress 都只接受"压缩器"接口
   （(context, question) → 压缩后 context），WSC 是引擎，不写适配器拿不到这两个分数。

## 下一阶段建议顺序

1. 定 adapter 的接口形态：把 WSC 的 checkpoint 生成包装成 summarizer，输入 (region, prompt) 输出文本。
   这是唯一能把 WSC 塞进两个 bench 的路径，也是把"自建 fixture 分数"换成"公开 bench 分数"的关键。
2. 用 BenchPress 的 M/EM/F1 口径做第一版适配器评测（46 MB、纯本地、零 API 就能验证通路）。
3. 再上 Compact-Bench retention（10 次调用/实例，便宜），最后才是 task track（要 Messages 开关）。
4. WSM 调参若还要做，只试 8–10 文件中间值，并且必须加步数上限——L 臂 62 分钟不收敛是前车之鉴。

## 环境备忘

- 分支 `codex/wsc-cooperative-compaction`；实验产物在 `dsh-wsc/experiments`。
- bench 仓库 clone 在 `experiments/bench/`（72 MB，已 gitignore，SHA 记在各 bench 报告里）。
- `web_fetch`/`web_search` 工具不可用（402 / 非公网 IP），但 `git` 与 Python `urllib` 的 HTTPS 正常。
- Python 用 `py -3.11`（`python` 是 WindowsApps 占位符，退出码 9009）。
- 模型走本地 gateway `http://127.0.0.1:8788`，OpenAI 兼容；密钥在 `~/.dsh/.credentials.yaml` 的 `refs.WD_API_KEY`。
