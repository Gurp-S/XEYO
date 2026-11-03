# WSC vs DSH 原生压缩：对照实验方案（执行版）

状态：已完成（P1–P5；结论见 `report/RESULTS.md`）

## 0. 决策摘要（已定，不再反复）

| 决策 | 取值 | 理由 |
|---|---|---|
| 压缩窗口 | 模型 `contextWindow = 65536`（64K），两个 profile 完全一致 | 用户指定 64K；窗口由 `llm-pi-ai` 配置决定，两种引擎读同一个值 → 唯一公平的容量控制点 |
| 何时开始压缩测试 | 先跑 pilot 校准：确认「调查阶段」token < ~45K，再正式跑 | 用户要求「不要一开始就 64K…让任务进入稳步执行时再开始」；若调查阶段就顶到 64K，两组都会退化，比较无意义 |
| 驱动方式 | `dsh --profile ab "task"`（headless，一次性跑完整个多阶段任务） | headless 不支持 resume/多轮注入；GUI 无自动化通道 |
| 分组 A | `compaction-basic` 启用，WSC 不加载 | DSH 原生 |
| 分组 B | `compaction-basic` 禁用，插入 `@xeyo/dsh-wsc`（mode=live, selection=selective, 协作式通知 80% / 强压 85%） | WSC 协作式压缩 |
| 工具集 | 两组完全相同；Windows 下用 `pwsh` 代替 `bash`（文档记录偏差） | 公平性优先于字面一致 |
| 重复次数 | 每场景每组 ≥3 次；预算允许再补到 5 次 | 用户要「广泛有代表性」 |

## 1. 环境与容量控制

- 模型：provider `wd` / model `deepseek-v4.1-flash`，baseURL `http://127.0.0.1:8788`（本地代理，凭据在 `$DSH_HOME/.credentials.yaml`）。
- 容量：patch `llm-pi-ai` → `providers.wd.models[0].contextWindow: 65536`，`maxTokens: 32768`（避免 output 上限 > 窗口）。**两个 profile 用同一段 patch**。
- Profile：复制 `$DSH_HOME/profiles/headless` → `ab`（只保留 base + headless 两个 bundle），`pnpm add link:D:/lea/XenYon code/dsh-wsc`。
- 每次运行前只替换 `ab/cordis.patch.yml`：
  - A 变体：仅容量 patch（basic 默认启用）。
  - B 变体：容量 patch + `- id: compaction-basic {disabled: true}` + `insert: @xeyo/dsh-wsc` 配置块。
- 会话数据：`$DSH_HOME/sessions/<id>/`（JSONL，含 `usage`、`compaction/*` 事件）；WSC 侧另写 `$DSH_HOME/wsc/{compactions,operations,evidence,understanding}.jsonl`。

## 2. 任务（自建小型仓库，含隐藏测试）

目标仓库 `experiments/fixture/`：一个迷你构建工具（零依赖 Node ESM），故意植入 4 个耦合缺陷 + 1 个后续扩展需求，使任务必然跨越多次压缩：

1. `lib/deps.js`：依赖图只记录显式 import，漏掉 CSS `url()` 与 JSON `extends` → 增量构建不失效（缺陷 1）。
2. `lib/cache.js`：缓存 key 只含 mtime 不含内容 hash → 同 mtime 改写不失效（缺陷 2）。
3. 删除源文件时缓存条目未清理 → 产物残留（缺陷 3）。
4. 中断恢复：写 manifest 非原子，进程被杀后 manifest 半写 → 下次构建崩溃（缺陷 4）。
5. 扩展需求：`--watch` 模式 + 并发 worker 上限（要求保持 CLI 参数、manifest v2 格式、输出顺序、symlink 语义、dry-run 不落盘、零新依赖）。

- 隐藏测试 `experiments/fixture/tests/hidden/*.test.mjs`：覆盖上述 5 项 + 约束项，运行 `node --test`。
- 任务提示词（固定文本，两组逐字相同）：给出分阶段指令（先读代码 → 修 1-4 → 加扩展 → 自测 → 汇总），并明确要求最终交付测试全绿。分阶段只体现在提示词里，由模型自主推进。

## 3. 指标

| 指标 | 来源 | 用途 |
|---|---|---|
| 输入/输出/缓存 token 累计 | 会话 JSONL `usage` | 成本 |
| 压缩次数、压缩触发点（上下文 token 值）、压缩耗时 | A: 会话 `compaction` 事件；B: `$DSH_HOME/wsc/compactions.jsonl` | 压缩行为 |
| 隐藏测试通过率 | 运行后跑 `node --test` | 正确性 |
| 约束项通过率 | 独立断言脚本（CLI 参数/格式/顺序/symlink/dry-run/依赖） | 回归风险 |
| 早期约束保留（recall） | 最终产物是否仍满足「提示词前 1/3 的约束」逐条检查 | 压缩后历史保留 |
| 重复劳动 | 相同命令重复次数、重复读同一文件次数 | 效率 |
| 失败/重试 | 工具错误数、LLM 重试数 | 稳定性 |
| 墙钟时间 | 运行起止 | 体感 |

## 4. 执行阶段

- [x] P1 建 fixture 仓库 + 隐藏测试 + 断言脚本；在无压缩（大窗口）下验证：满分可通过、缺陷确实存在。
  - 资产：`fixture/`（缺陷版，4 个耦合缺陷 + 缺 `--watch`/`--concurrency`）、`hidden/build.test.mjs`（9 项）、`solution/`（参考修复，仅用于验证测试可满分，不进入实验）、`score.mjs`（`node score.mjs <repo>` 输出 JSON 分数）。
  - 实测：`node score.mjs fixture` → 0.1111（1/9，仅「js 传递依赖」通过，符合预期）；`node score.mjs <fixture+solution>` → 1.0（9/9）。
  - 可见测试：`fixture` 自带 `tests/visible/basic.test.mjs` 2 项，在缺陷版与参考解上都通过（只做冒烟，不泄露缺陷）。
- [x] P2 建 `ab-a` / `ab-b` 两个 profile；各跑一次 smoke 确认加载正确、B 组压缩确实触发。
  - 位置：`C:\Users\48522\.dsh\profiles\ab-a`、`ab-b`，从 `headless` 复制骨架（`cordis.yml` 保持空数组）。
  - `package.json`：bundles 同为 `@deepseek-ai/dsh-base` + `@deepseek-ai/dsh-headless`；仅 `ab-b` 依赖 `@xeyo/dsh-wsc`（打包 tarball 安装，非 link，避免实验期间源码变动污染分组）。
  - `cordis.patch.yml` 两组逐字相同的前两段（`agent-default-model`: provider `wd` / model `deepseek-v4.1-flash` / reasoningEffort `high`；`llm-pi-ai`: baseURL `http://127.0.0.1:8788`、apiKeyEnv `WD_API_KEY`、`models[0].contextWindow: 65536`、`maxTokens: 32768`）。
  - 差异只在末段：`ab-a` 用原生 `compaction-basic`（`thresholdRatio 0.36621`、`retainRatio 0.05859`）；`ab-b` 关掉它，插入 `wsc-config`（`mode active`、`capacityMode tokens`、`capacityTokens 24000`、`retainRatio 0.16`、`notifyRatio 0.8`、`forceRatio 0.85`、`selection selective`）+ `wsc-engine`。
  - 偏差（相对本方案原文）：包名是 `@xeyo/dsh-wsc` 而非 `@xeyo/wsc-deepseek-harness`；B 组用 `mode active` 而非 `mode live`（live 只是通知模型自行调用，headless 下无人调用会退化为不压缩，A/B 会失真）；`compaction-basic` 不能整个 disabled —— `@deepseek-ai/dsh-command-compact` 等待 `compaction` 服务，关掉后插件树启动失败，故 A 组保留它、B 组由 WSC 提供服务。
- [x] P3 pilot：1M 窗口跑完整任务 1 次，测「调查阶段结束」与「任务结束」的 token 量 → 校准 64K 是否落在稳步执行段。
  - profile `ab-pilot`：`contextWindow 1048576`，`compaction-basic` 阈值 0.98（实际不触发，隔离压缩影响）。
  - 结果：988s，78 步 / 79 请求，得分 0.8889（8/9，仅 `--watch rebuilds after a source change` 失败）。
  - token 轨迹（`tools/context-estimate.mjs`，按 harness 回传的 assistant 文本 + 工具结果字符数估算，不含 reasoning，锚定首个请求 11487）：第 1 次写文件（第 5 步）时约 13.7K；结束时约 42K；峰值 42K。
  - 校准结论：调查阶段只占前 4 步（约 13.7K），任务主体在 13.7K–42K 之间。**压缩起点取 24000 tokens**：落在调查阶段之后、执行阶段中段，预计每次运行触发 1–2 次压缩；64K 窗口本身不会成为约束。
- [x] P4 正式矩阵：场景 × 分组 × 3 次（先 3 次，视预算补到 5 次）。已跑 3+3，见 `report/RESULTS.md`。
- [x] P5 汇总：`experiments/report/RESULTS.md`（表格 + 结论 + 代表性判断 + 局限），原始数据留档 `experiments/report/raw/`。

## 5. 已知风险与对策

- headless 默认模型 id 可能是旧的 `deepseek-v4-flash` → 首跑前核对 `ab` 的 `agent-default-model`，改为 `wd/deepseek-v4.1-flash`。
- 单次运行 token 成本高 → 先 pilot 估算单次成本，再决定重复次数；超预算则减场景不减每组次数。
- 64K 窗口可能触发 API 侧限制（max_tokens + 上下文）→ 已把 maxTokens 降到 32768。
- 若调查阶段就超过 64K → 视为 pilot 失败，改用「窗口 96K + 只测压缩后行为」的备选方案，并在报告中说明。
