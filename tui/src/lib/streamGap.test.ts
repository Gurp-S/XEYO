/**
 * streamGap.test.ts — TUI 收到 `stream_gap` 后的收尾判定，以及两个客户端入口真的接上了它。
 *
 * 缺陷形态（10-03 实测过同族）：一枪长回答中途掉线/被挤帧后，客户端把**缺段**当完整正文
 * 留下，用户（或管道下游的程序）看到 2/3 的答案还以为跑完了。后端在 `[DONE]` 之前发一帧
 * `stream_gap` 告知洞，TUI 原先**没有这个分支**
 * （见 python/tests/test_stream_contract_tui.py 里已摘牌的在册条目）。
 *
 * 管两件事：
 * 1. 判定本身——三臂（补齐/找不到/拉失败）都必须点名"缺了帧"，只有真补齐才准说"已补齐"；
 * 2. 接线——交互 App 与无头 `--json` 两条通路都必须调用它，否则"逻辑对了但没人接"
 *    就是第二个死分支（本项目反复踩的口径漂移）。
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  gapNote,
  gapThroughOf,
  lastAssistantText,
  lastAssistantTextFromRows,
  recoverAssistantAfterGap,
} from "./streamGap.js";
import type { TimelineItem } from "../types.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));

test("gapThroughOf：认得产品帧形状，别的帧一律不算洞", () => {
  // 反向校准：常见帧必须返回 0，否则每一枪都会白拉一次 transcript
  for (const xy of [
    { type: "usage", prompt_tokens: 1 },
    { type: "tool_result", name: "Read", output: "x" },
    { type: "reasoning_delta", text: "想想" },
    { type: "stream_gap_typo" },
  ]) {
    assert.equal(gapThroughOf(xy as Record<string, unknown>), 0, JSON.stringify(xy));
  }
  assert.equal(
    gapThroughOf({ type: "stream_gap", dropped_through_event_id: 2015 }),
    2015,
  );
  // 帧到了但号丢了：仍按"缺过"处理，不许退化成"没缺"
  assert.equal(gapThroughOf({ type: "stream_gap" }), 1);
  assert.equal(gapThroughOf({ type: "stream_gap", dropped_through_event_id: 0 }), 1);
});

test("取正文取的是最后一条，不是第一条；思考行不算正文", () => {
  const items: TimelineItem[] = [
    { id: "u1", kind: "user", text: "第一问" },
    { id: "a1", kind: "assistant", text: "上一轮的旧答案" },
    { id: "u2", kind: "user", text: "第二问" },
    { id: "a2", kind: "assistant", text: "本轮完整答案" },
  ];
  // 取第一条会拿上一轮冒充当前轮——正是"历史重放满足断言"那一族
  assert.equal(lastAssistantText(items), "本轮完整答案");
  assert.equal(lastAssistantText([{ id: "u1", kind: "user", text: "只有问" }]), null);

  const rows = [
    { role: "assistant", text: "旧正文" },
    { role: "assistant", text: "思考正文", isThought: true },
    { role: "user", text: "问" },
    { role: "assistant", text: "当前正文" },
  ] as const;
  assert.equal(lastAssistantTextFromRows(rows), "当前正文");
  assert.equal(
    lastAssistantTextFromRows([{ role: "assistant", text: "只有思考行", isThought: true }]),
    null,
    "整份 transcript 只剩思考行时要报『没找到』，不能把思考当正文补进去",
  );
});

test("三臂收尾：只有真补齐才准说已补齐，其余必须出声", async () => {
  const recovered = await recoverAssistantAfterGap({
    gapThrough: 2015,
    loadText: async () => "完整正文",
  });
  assert.equal(recovered.text, "完整正文");
  assert.match(recovered.note, /缺了帧/);
  assert.match(recovered.note, /已按服务端记录补齐/);

  const absent = await recoverAssistantAfterGap({
    gapThrough: 2015,
    loadText: async () => null,
  });
  assert.equal(absent.text, null);
  assert.match(absent.note, /缺了帧/);
  assert.doesNotMatch(absent.note, /已.*补齐/, "没拿到正文却报补齐＝面板说谎");
  assert.match(absent.note, /不完整/);

  const failed = await recoverAssistantAfterGap({
    gapThrough: 42,
    loadText: async () => {
      throw new Error("fetch failed: 502");
    },
  });
  assert.equal(failed.text, null);
  assert.match(failed.note, /缺了帧/);
  assert.match(failed.note, /补齐失败/);
  assert.match(failed.note, /fetch failed: 502/, "失败原因要带出来，不能只说失败了");

  // 三臂都得带得上事件号，否则同一回合里多次缺帧无法对账
  for (const outcome of ["recovered", "absent", "failed"] as const) {
    assert.match(gapNote(9, outcome), /事件 9/);
  }
});

test("接线：两条客户端入口都调用判定，缺帧不得静默", () => {
  const app = readFileSync(path.join(HERE, "..", "app", "App.tsx"), "utf8");
  assert.match(app, /gapThroughOf\(xy\)/, "onXy 没接 gapThroughOf ⇒ 帧仍会被静默丢弃");
  assert.match(app, /recoverAssistantAfterGap\(/, "onDone 没回拉正文 ⇒ 缺段被当完整内容留下");
  assert.match(app, /sysNote\(note\)/, "收尾结论没显示给用户");
  assert.match(app, /gapThroughRef\.current = 0/, "每枪要复位，否则上一枪的洞会传染下一枪");

  const json = readFileSync(path.join(HERE, "..", "runJson.ts"), "utf8");
  assert.match(json, /gapThroughOf\(xy\)/, "--json 通路没接 gapThroughOf");
  assert.match(json, /recoverAssistantAfterGap\(/, "--json 通路没回拉正文");
  assert.match(json, /type: "assistant_final"/, "--json 缺完整正文事件，下游只能拿残缺 delta 拼接");
  assert.match(json, /if \(text == null\) code = 1/, "补不到正文还退出 0＝把残缺结果当成功交给管道");
});
