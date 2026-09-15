# 删除记录：`reasoning_tail`（上一轮思考回顾注入）

> 2026-09-10。用户裁决「全删」。本文记录删除范围、理由与验证，供追溯。

## 1. 删了什么

把「上一轮思考回顾」这套机制**整体**移除，不是关掉开关：

| 层 | 移除内容 |
| --- | --- |
| 后端开关 | `permissions/policy.py`：`_reasoning_tail_ctx` / `set_reasoning_tail_enabled` / `reasoning_tail_enabled` / `_reasoning_tail_env_default` |
| 引擎 | `engine/query_loop.py`：import、`previous_reasoning_tail` 参数、捕获点（`reasoning_blob[-600:]`）、两处传参 |
| 注入器 | `prompt/pre_llm_inject.py`：`InjectContext.previous_reasoning_tail` 字段、注入块、白名单 `"reasoning_tail"` 登记 |
| 模式链路 | `memory/working.py`：`WorkingSnapshot.reasoning_tail`、序列化/反序列化、`resolve_modes` 参数与返回、`apply_modes` |
| HTTP | `server/routers/chat.py`：`ChatCompletionRequest.reasoning_tail`、`_effective_request_modes` 传参、`set_reasoning_tail_enabled` 两处调用 |
| CLI | `cli/config_store.py`：`CliConfig.reasoning_tail` + `validate_config_value` 分支；`cli/slash.py`：`/reasoning-tail` 处理器 |
| CLI 命令表 | `slash/registry.py`：`Command(name="reasoning-tail")`（并重新生成 `gui/src/generated/slashManifest.ts` 与 `tui/src/generated/slashManifest.ts`） |
| GUI | `settingsStore.ts`：字段/默认值/两处 hydrate/持久化；`SettingsModal.tsx`：整个开关 UI 块与选择器；`lib/api/chatStream.ts`：请求字段；`lib/slash.ts`：ghost hint |
| 测试 | 删除 `tests/test_reasoning_tail_switch.py`（专测）；清理 5 个文件里的功能用例；`test_background_text_guard.py` 白名单六类→五类 |

**残留**：`tui/src/components/AssistantBlock.tsx` 里的局部变量 `reasoningTail`
是「思考文本尾段显示」的 UI 变量（`reasoning.slice(-200)`），与本次删除的注入
机制**同名但无关**，保留。

## 2. 为什么删（三条，按重要性排序）

1. **与引擎铁律冲突。** AGENTS.md：「注意力里只出现信息，不出现导演」。该块是
   `directive` 类，措辞为「**你在上一轮模型调用中已经推理过，结尾如下（延续，
   不是新任务）**」——命令式，且「不是新任务」在替模型下判断。
2. **被历史回放通道覆盖。** 原始动机是「防弱模型重复思考」（让它知道上轮想到
   哪了）。但 2026-09-10 落地的 reasoning block 历史回放**已经把每条工具轮的
   完整 reasoning 原样回传**。再截 600 字符塞到对话尾部是**信息更少、措辞更强
   的冗余**。
3. **对标实现无此物。** 查 deepseek-harness 源码：只有 `ds_serialize.ts:200`
   的 `serializeAssistant`，reasoning 作为 block 原样回传，注释写官方规则
   「tool-call turns 必需，其余忽略」——**没有任何第二通道**。

**注意**：「弱模型存在旧结论指令化锚定压力」这个**判断本身是对的**，删的是
**方案**（用一段导演文本去解决），不是否定该判断。勿重新发明。

## 3. 影响面：产品行为变化

| 变化 | 说明 |
| --- | --- |
| GUI 设置 → 少一个开关 | 「上一轮思考回顾（建议仅弱模型）」整块消失 |
| `/reasoning-tail` 命令消失 | CLI/GUI/TUI 自动补全都不会再出现；命中该词会落入「未知命令」 |
| 环境变量 `XEYO_REASONING_TAIL` 失效 | 评测/脚本若用它开此功能，将不再有任何效果（静默） |
| 默认行为**不变** | 该功能**默认关**，故对绝大多数会话零行为差异 |

**唯一需要留意的**：如果某个评测配置显式设过 `XEYO_REASONING_TAIL=1` 或
GUI 里手动开过、并已写进 durable 模式记录 —— 那些记录里的 `reasoning_tail`
字段会被**静默忽略**（反序列化不再读它）。方向安全（旧记录不会 crash），
但如果曾靠它拿过分数，需要知道那个增益来源已不可复现。

## 4. 验证（2026-09-10）

| 检查 | 结果 |
| --- | --- |
| 全仓残留 grep（`python/` `gui/src/` `tui/src/`） | 仅剩上方说明的 TUI 同名局部变量 + 本记录/历史文档 |
| `tests/test_background_text_guard.py` 等 6 个受影响文件 | 69 passed（2 个 `typer` 缺失为既有环境问题） |
| 精准回归 12 文件（含 reasoning 双契约 + anthropic 适配器） | **155 passed** |
| 广度回归 `-k "prompt or policy"` | **117 passed** |
| `npx tsc --noEmit` | 0 error |
| `npx vitest run` | **743 passed / 5 failed**（与删除前基线逐条一致，全属既有） |

**关于 5 个 vitest 失败**：与本次删除前完全相同的集合（`mainPaths.workflow.test.tsx`
4 例 + `MessageList.chat.test.tsx` 1 例），根因是 `ModelPicker.tsx:122` 读
`s.profiles.find(...)` 得 `undefined`，属其他会话在途的 usage 改造，与本次无关。

## 5. 保留的历史文档

以下文档记录了**决策当时**的状态，未改写（历史记录应保持原貌）：

- `docs/最终方案-思考态回放.md:48` —— 已预警「删除时需同步处理
  `server/routers/chat.py` 的调用点，避免设置项失效引发前端异常」。本次删除
  覆盖了该提示的全部范围。
- `docs/全仓优化点扫描-成本导向.md:29` —— 记录了该开关默认关时的原始理由。
- `docs/Anthropic-Gemini支持方案与reasoning压缩域决策.md:182` —— 明确区分了
  「跨厂商思考态适配」与「往 T_now 注入上一轮思考尾段」是两件不同的事。
