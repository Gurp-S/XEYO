# Compact-Bench：1 个 instance 与预算

2026-11-04 05:20–05:50。仓库 `github.com/cai-jianfeng/compact-bench`，
commit `9dd9a3f5a91b2de5acdf56cee2fc0a4d16dcefc5`，clone 在 `experiments/bench/compact-bench`
（已 gitignore，不入库）。

## 实际跑了什么

| 运行 | 命令 | 结果 | API 调用 |
|---|---|---|---|
| production 全量 | `run.py --track production` | 106 条链，R₁=15.7%、R₂=19.9%、R₃=4.9%、R₄=1.8%，时序错乱 0% | 0 |
| retention 机械基线 | `run.py --track retention --baseline-only` | 146 会话，anchor_index 召回 79.1% | 0 |
| retention 1 个 instance（2 会话） | `--track retention --model deepseek-v4.1-flash --limit 2` | 见下表 | 10 |

retention 的 2 会话结果（claude-code，五种生产 prompt）：

| variant | 召回 |
|---|---|
| codex | 13.7% |
| opencode | 14.5% |
| gemini | 7.1% |
| kimi | 5.8% |
| anchor_index（机械上界） | 93.8% |

## 预算（实测）

| 项 | 量 |
|---|---|
| 数据集 | 全量 205 MB（80 个文件）；production track 只下 5 MB |
| production track | ~40 s，零 API |
| retention 机械基线 | ~10 s，零 API |
| retention 2 会话 | ~60 s，10 次 chat 调用 |
| retention 全量 | 146 会话 × 5 prompt = 730 次调用（按 2 会话 10 次线性外推约 1 小时） |
| task track | **未跑**：需要 Messages 端点 + 每个 repo 一套 pip 环境（数百 MB） |

## 关键判断：这个 bench 测的不是 WSC

Compact-Bench 的被测对象是**摘要模型/摘要 prompt**（`--model` 是模型 ID，五种 prompt 是
claude/codex/opencode/gemini/kimi），不提供"压缩引擎"接口。WSC 是一条自己的压缩流水线
（选材请求 + checkpoint 组装），没有可以塞进 `--model` 的适配器。
所以哪怕把 task track 跑通，得到的也是"某个模型当摘要器时的保留率"，不是 WSC 的分数。

要真正把 WSC 放进这个 bench，得写一个适配器：把 WSC 的 checkpoint 生成过程包装成一个
"summarizer"，接收 (region messages, prompt) 返回摘要文本。这是新工作量，需要你确认要不要做。

## task track 的硬阻塞

gateway 明确拒绝：

    Anthropic Messages is disabled by default: this gateway translates requests to
    Chat Completions and ignores cache_control... Enable it in the Settings panel
    or set WB_ENABLE_ANTHROPIC_MESSAGES=1 to opt in at your own risk (see issue #367).

task track 的续跑 agent 只走 Messages 协议，chat completions 不能替代。
解锁方式（需要你决定，因为警告里写了会放大额度消耗）：在 gateway 侧设
`WB_ENABLE_ANTHROPIC_MESSAGES=1` 并重启，或在 Settings 面板里打开。

## 结论

- 预算确认完毕：**数据 205 MB、零 API 的两个 track 几十秒跑完、retention 单实例 10 次调用/1 分钟**。
- 可扩展的是 retention（便宜、已验证通路），但它测模型不测引擎。
- task track 与"给 WSC 打分"都需要额外条件（前者要 Messages 开关，后者要写适配器）。
