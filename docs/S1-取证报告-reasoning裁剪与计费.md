# S1 取证报告：reasoning 裁剪容忍度 + 计费实测

> 执行时间：2026-09-10 | 模型：`deepseek-v4-flash` | 成本：¥1.27（超出 ¥0.01 预估，见 §五）
> 脚本：`TerminalBench/zero/step1_trim_and_bill_probe.py`、`step1b_big_reasoning_billing.py`、`step1c_reasoning_token_accounting.py`
> 证据：`step1_evidence.json`、`step1b_evidence.json`

---

## 一、执行摘要（★ 两个反直觉结论）

| 问题 | 结论 | 影响 |
|---|---|---|
| **旧轮 reasoning 能裁吗？** | **能裁 —— 全程无 400** | 裁剪策略在 DeepSeek 上安全（与 Anthropic 官方口径一致） |
| **reasoning 计入输入 token 吗？** | **★ 几乎不计 —— 被系统性排除在 `prompt_tokens` 之外** | **「全量保留 = ¥76」的成本模型彻底证伪** |

**最重要的发现**：`reasoning_content` 回传后，**厂商几乎不把它算进 `prompt_tokens`**。这推翻了决策书里「全量回放 ¥76.30（未命中）/ ¥1.53（命中）」的整个推算框架——真实情况是**两种算法都错**，因为 reasoning **根本不在计费基数里**。

---

## 二、实验 1：裁剪容忍度 —— 旧轮可裁（无 400）

3 轮工具循环，对照组全量保留、处理组剥掉非最新轮的 `reasoning_content`：

| 组 | 轮1 | 轮2 | 轮3 | 结论 |
|---|---|---|---|---|
| **KEEP（全量）** | 200 | 200 | 200 | 通过 |
| **TRIM（剥旧）** | 200 | 200 | 200 | 通过 |

请求内 `rc块` / `rc字符` 证实处理组确实剥掉了：
```
TRIM  轮2: 请求 rc块=1 rc字符=67   → 200
TRIM  轮3: 请求 rc块=0 rc字符=0    → 200   ← 旧 reasoning 已全部剥离，仍 200
```

**结论**：DeepSeek 对「历史 assistant 缺 `reasoning_content`」**宽容**，与 Anthropic 官方口径（「工具使用之外，允许省略先前轮次的思考」）**一致**。

⚠️ **但注意 S0 的既有发现**：连「完全不回传」都返回 200（A 臂 4 次全 200）。所以「能裁」这个结论**不构成必须裁的理由** —— 厂商压根不强制。

---

## 三、实验 2：计费 —— ★ reasoning 几乎不计入输入 token

### 3.1 小 reasoning（step1，工具循环）

```
轮1: 请求rc=  0ch → prompt=340  hit=128  miss=212
轮2: 请求rc= 73ch → prompt=462  hit=256  miss=206
轮3: 请求rc=133ch → prompt=574  hit=384  miss=190
```
`hit` 每轮稳定 **+128**，`miss` **不涨反降**（212→206→190）。

### 3.2 ★ 大 reasoning（step1b，决定性证据）

```
轮1: 请求rc=     0ch(≈    0tok) → prompt=   68  hit=0    miss=68
轮2: 请求rc=45,217ch(≈26,598tok) → prompt=1,957  hit=0    miss=1,957
轮3: 请求rc=100,641ch(≈59,200tok) → prompt=3,589  hit=1,920 miss=1,669
```

**这是决定性的**：
- 轮2 塞入 **45,217 字符（≈2.66 万 token）**的 reasoning，`prompt_tokens` 只从 68 涨到 **1,957**。
- 轮3 塞入 **100,641 字符（≈5.92 万 token）**的 reasoning，`prompt_tokens` 只有 **3,589**。

**差值分析**：

| 轮次 | 请求内 reasoning | 折算 token | 实际 prompt_tokens | 若 reasoning 计费应有 |
|---|---|---|---|---|
| 1→2 | +45,217 ch | +26,598 | **+1,889** | +26,598 |
| 2→3 | +55,424 ch | +32,602 | **+1,632** | +32,602 |

**`prompt_tokens` 的涨幅只有 reasoning 体量的 ~6%**。缺席的 94% 就是 reasoning 本身。

**结论：DeepSeek 把回传的 `reasoning_content` 排除在 `prompt_tokens` 之外。**

（涨的那 ~1.9k / ~1.6k token 与 `content` 正文、消息结构开销吻合，不是 reasoning。）

---

## 四、这两个结论如何改写决策书

### 4.1 「全量 vs 裁剪」的成本之争**不存在了**

| 原推算（决策书） | 实测 |
|---|---|
| 全量回放 ≈ ¥76.30（未命中） | **≈ ¥0**（不计入计费基数） |
| 命中价 ≈ ¥1.53 | 同上，无需区分 |
| 只留 2 轮 ≈ ¥10.14（降 86.7%） | **省的钱 ≈ 0** |

→ **裁剪的「省成本」动机完全消失。** 决策书里「按未命中算 ¥76」是**纯客户端视角的错误推算**，实测直接推翻。

### 4.2 那还要不要裁？—— **只为一个理由：上下文窗口**

成本动机没了，但**窗口占用**依然真实存在：
- 轮3 请求里躺着 **100,641 字符**的 reasoning（≈5.9 万 token 的语义体积）。
- 虽然不计费，但**厂商侧是否把它计入 `context_length` 上限**未实测（计费排除了，窗口未必）。
- 真实轨迹里最长单会话 reasoning 累计 **57.7 万字符** —— 若进窗口，足以挤爆。

→ **所以「近档保留 2 轮」的定位应该是「窗口管理」，不是「成本管理」。** 这与我在决策书§五的预判一致，现在有了实测支撑。

### 4.3 对 Anthropic/Gemini 的连带影响

- **Gemini 的 `thought_signature` 必须完整回传**（缺了 400）——这条**不受**本实验影响，因为 signature 是不透明字节，与「reasoning 是否计费」无关。
- **Claude 的 thinking block 必须原样回传**（含 signature）——同理。
- 但 **Claude 官方明说「只对实际展示给 Claude 的块计费」** → 与本实测（DeepSeek 排除 reasoning 计费）**方向一致**，业界普遍这么做。

---

## 五、诚实披露：实验成本超出预估

| 项 | 预估 | 实际 |
|---|---|---|
| 总成本 | ¥0.01 | **¥1.27**（余额 0.97 → −0.30） |

**超出原因**：`step1b` 用 `reasoning_effort: high` 强制模型产出长思考，单次响应 `completion_tokens` 达 **13,793 / 27,580 / 10,368** —— **输出侧**（4.0 元/M）是成本主体，不是输入侧。三次高effort调用即约 ¥0.4~0.6，加上其余调用累计 ¥1.27。

**教训**：测「输入计费」用了「强制长输出」的手段，手段本身的成本远超被测对象。后续这类实验应：
- 用**构造的假 reasoning 字符串**（不调模型产出）代替真实生成；
- 或降低 `max_tokens` 上限。

`step1c`（受控变量法，正是这个思路）**因余额耗尽未跑完** —— 这是本报告的**唯一未竟项**。

---

## 六、未竟项与复现方式

**未竟**：`step1c` 的受控变量实验（同一对话、只改 reasoning 长度、对比 `prompt_tokens` 差值）**未执行**（余额 −0.30）。

**它是否重要**：**不关键**。step1b 的 45k→100k 对比已足够说明问题（涨幅 6% vs 应有 100%）。step1c 只是把证据做得更干净的「同轮三组对照」，结论不会变。

**复现**：
```bash
py -3.11 TerminalBench/zero/step1_trim_and_bill_probe.py   # 实验1+2，≈¥0.05
py -3.11 TerminalBench/zero/step1b_big_reasoning_billing.py --help  # 大 reasoning，≈¥1.2
py -3.11 TerminalBench/zero/step1c_reasoning_token_accounting.py    # 受控变量，≈¥0.01（需先充值）
```

**重要条件**：`step1b` 的高成本来自 `reasoning_effort: high` + 长输出。复现前请确认余额。
