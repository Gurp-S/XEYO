import type { TimelineItem } from "./types.js";

/** 离线演示 —— 无需后端服务器的 XEYO 风格时间线。 */
export async function runDemoTurn(
  onItems: (items: TimelineItem[]) => void,
  signal?: AbortSignal,
): Promise<void> {
  const sleep = (ms: number) =>
    new Promise<void>((resolve, reject) => {
      const t = setTimeout(resolve, ms);
      signal?.addEventListener("abort", () => {
        clearTimeout(t);
        reject(new DOMException("aborted", "AbortError"));
      });
    });

  let items: TimelineItem[] = [
    {
      id: "u1",
      kind: "user",
      text: "请把个人中心用户头像改成圆形",
    },
  ];
  onItems(items);

  await sleep(400);
  items = [
    ...items,
    {
      id: "a1",
      kind: "assistant",
      text: "先定位头像组件，再改成圆形裁剪。",
      streaming: true,
    },
  ];
  onItems(items);

  await sleep(500);
  items = [
    ...items.filter((i) => i.id !== "a1"),
    {
      id: "a1",
      kind: "assistant",
      text: "先定位头像组件，再改成圆形裁剪。",
      streaming: false,
    },
    {
      id: "t1",
      kind: "tool",
      name: "Glob",
      summary: "**/UserAvatar*",
      status: "running",
    },
  ];
  onItems(items);

  await sleep(600);
  items = items.map((i) =>
    i.id === "t1"
      ? {
          ...i,
          status: "completed" as const,
          result: "gui/src/components/profile/UserAvatar.tsx",
        }
      : i,
  );
  onItems(items);

  await sleep(400);
  items = [
    ...items,
    {
      id: "t2",
      kind: "tool",
      name: "Edit",
      summary: "gui/src/components/profile/UserAvatar.tsx",
      status: "running",
    },
  ];
  onItems(items);

  await sleep(700);
  items = items.map((i) =>
    i.id === "t2"
      ? {
          ...i,
          status: "completed" as const,
          result: "Added rounded-full · removed rounded-md",
        }
      : i,
  );
  onItems(items);

  await sleep(400);
  items = [
    ...items,
    {
      id: "a2",
      kind: "assistant",
      text:
        "已把 UserAvatar 换成 rounded-full，头像现在是圆形。可在个人中心刷新确认。",
      streaming: false,
    },
  ];
  onItems(items);
}
