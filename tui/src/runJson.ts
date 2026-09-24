/**
 * 机器可读的无头对话 —— 质量门：--json 绕过全部 TUI 装饰。
 * 每行向 stdout 输出一个 JSON 对象（NDJSON）。
 */
import {
  applyXy,
  createSession,
  healthOk,
  interruptSession,
  resolvePermission,
  streamChat,
  type ChatBody,
} from "./api/sse.js";
import type { CliConfig, TimelineItem } from "./types.js";

function emit(obj: Record<string, unknown>): void {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

export async function runJsonChat(
  config: CliConfig,
  prompt: string,
): Promise<number> {
  const text = prompt.trim();
  if (!text) {
    emit({
      type: "error",
      message: "--json requires a prompt argument",
      fix: 'xeyo --json "your message"',
    });
    return 2;
  }

  const ok = await healthOk(config.baseUrl);
  if (!ok) {
    emit({
      type: "error",
      message: `Cannot reach ${config.baseUrl}`,
      fix: "py -3.11 -m cli serve --cwd <project>",
    });
    return 1;
  }

  // T31：会话 id 由服务端签发（消除客户端自造 UUID）。
  let sessionId = config.sessionId;
  let cwd = config.cwd;
  if (!sessionId) {
    try {
      const created = await createSession(config.baseUrl, config.apiKey, config.cwd);
      sessionId = created.session_id;
      cwd = created.cwd || cwd;
    } catch (e) {
      emit({ type: "error", message: `create session failed: ${String(e)}` });
      return 1;
    }
  }

  emit({
    type: "session",
    session_id: sessionId,
    cwd,
    provider: config.provider,
    model: config.model || "deepseek-chat",
    agent_mode: config.agentMode,
  });

  const body: ChatBody = {
    model: config.model || "deepseek-chat",
    stream: true,
    session_id: sessionId,
    provider: config.provider,
    // T31：默认模式不发送，交由会话 durable 记录裁决；仅显式非默认才覆盖。
    ...(config.permissionMode && config.permissionMode !== "risk"
      ? { permission_mode: config.permissionMode }
      : {}),
    ...(config.agentMode && config.agentMode !== "agent"
      ? { agent_mode: config.agentMode }
      : {}),
    workspace: cwd,
    messages: [{ role: "user", content: text }],
  };

  let items: TimelineItem[] = [];
  let id = 0;
  const nextId = () => `j${++id}`;
  let code = 0;
  const ac = new AbortController();

  await new Promise<void>((resolve) => {
    // Ctrl+C 必须同时打断服务端：只断本地读流会留下一轮还在跑的引擎作业。
    const onInt = () => {
      code = 1;
      emit({ type: "interrupted", message: "SIGINT: aborting local stream and server turn" });
      ac.abort();
      void interruptSession(config.baseUrl, config.apiKey, sessionId).catch(() => {
        /* 服务端可能已经结束；不掩盖已经发生的中断 */
      });
    };
    process.on("SIGINT", onInt);
    const finish = () => {
      process.off("SIGINT", onInt);
      resolve();
    };
    void streamChat(
      config.baseUrl,
      config.apiKey,
      body,
      {
        onDelta: (chunk) => {
          emit({ type: "assistant_delta", text: chunk });
        },
        onXy: (xy) => {
          emit({ type: "xy", ...xy });
          const kind = String(xy.type ?? "");
          if (kind === "permission_pending") {
            // 无头 JSON 模式下默认拒绝（无 TTY 交互提示）。
            const requestId = String(xy.request_id ?? "");
            emit({
              type: "permission_denied",
              request_id: requestId,
              tool: xy.tool_name,
              reason: "no TTY; fail-closed",
              fix: "Use interactive TUI to approve, or permission_mode=never",
            });
            code = 1;
            // 只在本地宣布拒绝是没用的：服务端还挂在这条请求上等决议，
            // 于是"fail-closed"变成无限等待。决议必须回给服务端。
            if (requestId) {
              void resolvePermission(config.baseUrl, config.apiKey, requestId, "deny").catch(
                (e: unknown) => {
                  emit({ type: "error", message: `deny failed: ${String(e)}` });
                },
              );
            }
          }
          items = applyXy(items, xy, nextId);
        },
        onDone: () => {
          emit({ type: "done", ok: code === 0 });
          finish();
        },
        onError: (err) => {
          emit({
            type: "error",
            message: err.message,
            fix: "Check engine logs and network; retry with xeyo serve running",
          });
          code = 1;
          finish();
        },
      },
      ac.signal,
    ).catch((err: unknown) => {
      emit({
        type: "error",
        message: String(err),
        fix: "Check engine logs and network",
      });
      code = 1;
      finish();
    });
  });

  return code;
}
