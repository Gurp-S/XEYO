# WSC 为什么在对照实验里输得这么彻底：根因分析

数据来源：`report/raw/` 的 6 次运行、140 份 WSC 检查点、40 份原生摘要、`$DSH_HOME/wsc/compactions.jsonl` 账本、WSC 源码。

## 一句话

WSC 的检查点是**「证据保真」设计**——只保留逐字引用；它没有「任务状态」的位置。碰上一条 1345 字符的任务提示词，控制段的 800 字符硬上限正好把「要实现什么」切掉，于是每次压缩都把**任务**换成了**看过的代码**。这不是概率性损失，是结构性丢失：140 份检查点里 `--watch` 出现 0 次，原生 40 份里出现 40 次。

## 第一层：任务在第一次压缩就没了（100% 复现）

`lib/checkpoint.js:57`：

```js
const SECTION_ITEM_CAP = {
  ...
  users: 800,   // 每条用户消息最多 800 字符
  ...
}
```

这个上限在**两条路径上都生效**：deterministic 走 `takeWithin(trimmed[key], allocation, SECTION_ITEM_CAP[key])`（第 278 行），selective 走 `caps.control = 800`（第 464、468 行）。

实测提示词 1345 字符，关键位置：

| 内容 | 起始下标 |
| --- | --- |
| `--watch`（请求的特性） | **819** |
| `Constraints that must keep holding`（必须守住的约束） | **950** |

800 的截断点落在缺陷 4 中间，检查点里留下的是字面断句 `…crashes the ne`：

```
## User requests (verbatim, control)
- Work in this repository. … 4. A build interrupted while the manifest is being written
  leaves a half-written manifest that crashes the ne
```

统计（`tools` 里的扫描脚本，扫 `compaction/summary` 文本）：

| run | 检查点数 | 含 `--watch` | 含 `--concurrency` | 出现截断断句 |
| --- | --- | --- | --- | --- |
| a-1 / a-2 / a-3（原生） | 11 / 20 / 9 | 11 / 20 / 9 | 11 / 20 / 9 | 0 |
| b-1 / b-2 / b-3（WSC） | 24 / 96 / 20 | **0 / 0 / 0** | **0 / 0 / 0** | 6 / 5 / 5 |

连 selective 路径也躲不过：b-2 第一份检查点（`provider=wd model=deepseek-v4.1-flash`）的控制段同样断在 `crashes the ne`。

**后果**：模型从头到尾不知道要加 `--watch`/`--concurrency`。三个 B 组运行全部没实现这两个特性，正是隐藏测试里对应失败的两条。约束段同样被切掉，所以 2/3 次连 `--dry-run` 不落盘、manifest 结构、确定性输出这些开头的约束也一起破了。

## 第二层：检查点模板里没有「当前工作 / 下一步」

WSC 的 section 集合（`checkpoint.js:14-25`）：`prior / users / developers / selected / judgments / errors / outputs / decisions / calls / files / verification`。全是「过去发生了什么」，没有「现在在哪、接下来做什么」。

原生摘要有明确的任务状态段。同一次运行的末次检查点对比：

| b-1 末次检查点（2358 字符） | a-1 末次检查点（17283 字符） |
| --- | --- |
| Prior checkpoint 1263 | Primary Request and Intent 1442（含特性 + 约束） |
| Selected excerpts 904 | Key Technical Concepts 1435 |
| Recorded judgments 189 | Files and Code 8113 |
| — | Errors and Fixes 1879 |
| — | **Pending Jobs 413** |
| — | **Current Work 1832** |
| — | **Next Step 280** |
| — | Critical Context 1882 |

WSC 的 2358 字符里，**零字节**说明「我在修第几个缺陷、还剩什么」。所以压缩后的模型只能靠重读文件重新推断进度。

## 第三层：selective 路径 69% 根本没跑起来

`compactions.jsonl` 174 行：`model=deterministic` **120 行**，`model=deepseek-v4.1-flash` 54 行（31%）。即「让模型选材」这个设计在 2/3 的压缩里没生效，直接退化成规则抽取。

退化的判定点（`engine.js:615-644`）：选材请求 `maxTokens: MAX_SELECTION_TOKENS = 4096`，输出必须是一个严格 JSON（`lib/selection.js` 的 `SELECTION_INSTRUCTION`，要求 8–1200 字符的逐字引用）。成功的那 54 次实际用了 1400–3100 output tokens——余量本就不大，而这个模型是推理模型（`reasoningEffort: medium`），推理 token 与 JSON 共用这 4096。一旦推理拉长，JSON 被截断，`parseSelection` 解析失败 → 返回 `null` → 退化为规则抽取。日志被 headless 吞掉，所以这个 69% 一直没被发现。

即使跑通，选出来的东西也不对。b-2 第一份 selective 检查点选了这些「用户引用」：

```
- [s1] [user] 协作方式：后续工作由当前代理直接完成，不使用子代理。
- [s2] [user] 6. **任务完成：** 反问自己:是否解决用户的问题?…
- [s3] [assistant] I'll start by exploring the repository structure and reading the code.
```

选材模型把仓库 `AGENTS.md` 的规范条文当成了任务要求——它按「逐字、可引用」打分，而任务状态本来就不在它的目标函数里。

## 第四层：压缩抖动与重读放大

`retainRatio 0.16 × capacityTokens 24000 = 3840` tokens 的保留量，实际被填进约 700 tokens（2.3K 字符）的检查点，剩下的预算没用上。压缩后模型只剩「几段代码引用」，于是重新探索：

| 指标 | A（原生） | B（WSC） |
| --- | --- | --- |
| 重复读同一文件 | 17 / 29 / 8 | 93 / 333 / 45 |
| 压缩次数 | 14 / 22 / 10 | 26 / 105 / 24 |
| 步数 | 36 / 71 / 50 | 68 / 297 / 72 |
| 输入 token | 165K / 301K / 154K | 305K / 1033K / 244K |
| 墙钟 | 699 / 920 / 486 s | 775 / 2673 / 713 s |

重读把上下文重新填满（约 20 步回到 24K 触发线），触发下一次压缩，而下次压缩又把「刚刚搞清楚的事」换成新的几段引用——b-2 在这个环里转了 105 圈、297 步、44 分钟。压缩省下的 token 被重读和额外轮次全吃回去还有余，这是输入 token 反而高 1.8 倍的原因。

## 结论：三层结构性缺陷，不是调参问题

1. **控制段 800 字符上限**——任务说明被物理截断，特性与约束从未进入任何检查点。这是单点、可复现、影响最大的一条。
2. **检查点没有任务状态段**——模板只记录「发生过什么」，不记录「还差什么」，即使引用完整也无法表达进度。
3. **selective 输出预算 4096 与推理模型冲突**——设计上的主力路径 2/3 时间不可用，退化成规则抽取，且退化是静默的。

第 1、3 条是常量，第 2 条是模板设计。把 `users` 上限提到 4000、给检查点加 `## Current work` / `## Next step` 两个段、把 `MAX_SELECTION_TOKENS` 提到 8192 或对选材请求关闭推理，是三个各自独立、可分别验证的改动。按这三条改完再跑同一组 A/B，才能判断 WSC 的「逐字引用」路线本身有没有价值——现在这组数据测出来的主要是「任务被截断了」，而不是「协作式压缩好不好」。
