/**
 * Machine-readable headless chat — quality gate: --json bypasses all TUI chrome.
 * Emits one JSON object per line (NDJSON) on stdout.
 */
import {
  applyXy,
  createSession,
  healthOk,
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

  await new Promise<void>((resolve) => {
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
            // Fail-closed in headless JSON (no TTY prompts).
            emit({
              type: "permission_denied",
              request_id: xy.request_id,
              tool: xy.tool_name,
              reason: "no TTY; fail-closed",
              fix: "Use interactive TUI to approve, or permission_mode=never",
            });
            code = 1;
          }
          items = applyXy(items, xy, nextId);
        },
        onDone: () => {
          emit({ type: "done", ok: code === 0 });
          resolve();
        },
        onError: (err) => {
          emit({
            type: "error",
            message: err.message,
            fix: "Check engine logs and network; retry with xeyo serve running",
          });
          code = 1;
          resolve();
        },
      },
    ).catch((err: unknown) => {
      emit({
        type: "error",
        message: String(err),
        fix: "Check engine logs and network",
      });
      code = 1;
      resolve();
    });
  });

  return code;
}
