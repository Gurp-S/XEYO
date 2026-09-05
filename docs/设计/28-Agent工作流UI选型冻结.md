# Agent 工作流 UI · 选型冻结

> 状态：**已冻结 · 终稿**（2026-08-28）  
> 落地必须严格按本文件；动词态切换动画必须与 **A8 Morph** 预览像素级一致（见下）。

## 底座（不可改）

| 层 | 选型 | 说明 |
|----|------|------|
| 布局 | **#10 Split header** | 左动词 / 右预览；顶栏 Working/Done + 右侧 meta |
| 进行中 | **A7 Timer + A8 Morph** | 顶栏 `mm:ss`；动词态切换见「A8 合同」 |
| Thinking | **L10 Elastic snap** | 单行；片段弹入 + 弹性跟滚 |
| 骨架 | 树形展开 + 工具详情 | `grid` `0fr→1fr`；Args/Output |
| 收尾 | **`done on {timestamp}`** | 最终回复后折叠；可再展开 |

### A8 Morph 合同（严格）

实现必须与 `gui/workflow-anim-preview.html` 中 A8 一致：

```css
.morph { display: inline-grid; position: relative; }
.morph > span {
  grid-area: 1 / 1;
  transition: opacity 0.35s ease, transform 0.35s ease;
}
.morph > span.off {
  opacity: 0; transform: translateY(4px); pointer-events: none;
}
.morph > span.on {
  opacity: 1; transform: translateY(0);
}
```

- 两层同格文字，用 `.on` / `.off` 切换；**禁止**用别的 fade/slide 替代。  
- 适用于：`Thinking↔Thought`、`Editing↔Edited`、以及结果落定 `Editing→Failed`（同一套 morph，失败态着色另加，不另做动画曲线）。  
- **点子 2 H2** 只是目标行的短暂色闪，**不得**替换或改写 A8 morph。

## 增强 1–8（全部采纳 · 终稿口径）

| # | 点子 | 冻结口径 |
|---|------|----------|
| 1 | 词来源分层 | 结论词 primary / 路径次级 secondary |
| 2 | 交接 | **H2 动词柔闪**（accent 色闪一下）；与 A8 分离。触发：①下一工具入轨；②Thought 词命中 detail（路径/标识符/中文短名） |
| 3 | 收尾微交互 | 折叠前末词淡出 → `done on {timestamp}` |
| 4 | 结果态 | **同一工具行**：进行中 `Editing`；成功 A8→`Edited`；失败 A8→`Failed`（危险色）。无独立错误步骤 |
| 5 | 悬停偷看 | hover Thought 右栏浮层近句 |
| 6 | 静音档 | `smoothness=off`：关 L10/A8 动画与 H2；A7 仍显示时长 |
| 7 | done 可读增强 | 折叠行右侧淡色 `N steps · +X −Y` |
| 8 | 子 Agent | **去掉 `InlineAgentChips` 卡片**。每个子 Agent = **一条 done 风格栏位**（与收尾行同级视觉语言），**只显示文字输出**；**点击跳转子 Agent 界面**。进行中亦用同一栏位滚/显文字，不恢复卡片 |

## 明确不做

- 多行 Thought 默认进行中展示  
- 折叠摘要前缀 `>`  
- 固定长文 marquee 冒充 Thinking  
- 偏离 Split header 的默认骨架  
- 独立 Failed 步骤卡片  
- 子 Agent 独立 chip/卡片入口（改由 done 栏位点击进入）

## 预览归档

- `gui/workflow-anim-preview.html` — **A8 动画真源**
- `gui/workflow-thinking-line-preview.html` — L10
- `gui/workflow-ideas-preview.html` — 8 点子初版
- `gui/workflow-revise-2-4-8-preview.html` — 2/4/8 修订
- `gui/workflow-freeze-final-preview.html` — **终稿合成预览（落地对照）**

## 落地入口

- `gui/src/components/ActivityLog.tsx` — Split / A7 / L10 / 1–7（点子 5 hover peek 已恢复）
- `gui/src/components/activity/MorphVerb.tsx` — A8 Morph + ThoughtTicker
- `gui/src/components/AgentDoneBars.tsx` — 点子 8（完成态优先 `result` 文字输出）
- `gui/src/components/AssistantTurn.tsx` / `MessageList.tsx` — 单顶 Working、live→done 交叉过渡
- `gui/src/components/InlineAgentChips.tsx` — deprecated
- `gui/src/lib/toolActivity.ts` — `done on`（完成时刻 = 末条 createdAt）+ Failed 动词
- `gui/src/index.css` — 冻结样式

### 已冻结补充口径（2026-08-29）

- 取消段级 `Explored N files` 汇总头；折叠为 `N steps` / Thought 时长
- 同 turn 仅最上一条 Working；后续 activity `hideHeader`
- **进行中整轮**：仅最新 turn 显示 Working；更早 turn 的 activity 全部无顶栏（避免叠头）
- **Thought→工具**：同一 `${turnId}-rail` 稳定挂载，禁止 thought-only remount 闪断
- 工具入轨：短延迟透明度渐变；**Thought/Thinking 不参与**
- 空 reasoning 不拿 `briefly`/`Ns` 冒充 L10 文案（仅 blink）
- **H2**：下一工具入轨即动词柔闪；Thought 词命中扩展为路径/标识符/中文短词（须落在 detail）
- `done on` 禁止墙钟 `Date.now()` 冒充完成时间
- 点子 5：Thought hover 近句 peek（smoothness=off 关闭）
- 点子 8：完成态优先 `result` 文字输出
