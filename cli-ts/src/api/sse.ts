import type { TimelineItem, TodoRow, UsageInfo } from "../types.js";

export type SseHandlers = {
  onDelta: (text: string) => void;
  onXy: (xy: Record<string, unknown>) => void;
  onDone: () => void;
  onError: (err: Error) => void;
};

function parseDataLine(line: string): Record<string, unknown> | null {
  let s = line.trim().replace(/^\uFEFF/, "");
  if (s.endsWith("\r")) s = s.slice(0, -1);
  if (!s.startsWith("data:")) return null;
  const payload = s.slice(5).trim();
  if (!payload || payload === "[DONE]") return null;
  try {
    const obj = JSON.parse(payload) as unknown;
    return obj && typeof obj === "object" ? (obj as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

export function* iterSseObjects(chunks: Iterable<string>): Generator<Record<string, unknown>> {
  let buf = "";
  for (const chunk of chunks) {
    buf += chunk.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    while (buf.includes("\n")) {
      const i = buf.indexOf("\n");
      const one = buf.slice(0, i);
      buf = buf.slice(i + 1);
      const obj = parseDataLine(one);
      if (obj) yield obj;
    }
  }
  if (buf.trim()) {
    const obj = parseDataLine(buf);
    if (obj) yield obj;
  }
}

export function deltaText(obj: Record<string, unknown>): string {
  const choices = obj.choices;
  if (!Array.isArray(choices) || !choices[0] || typeof choices[0] !== "object") {
    return "";
  }
  const c0 = choices[0] as Record<string, unknown>;
  const delta = c0.delta;
  if (delta && typeof delta === "object") {
    const content = (delta as Record<string, unknown>).content;
    if (typeof content === "string") return content;
  }
  return "";
}

export function extractXy(obj: Record<string, unknown>): Record<string, unknown> | null {
  for (const key of ["xy", "xeyo"] as const) {
    const val = obj[key];
    if (val && typeof val === "object") return val as Record<string, unknown>;
  }
  return null;
}

export type ChatBody = {
  model: string;
  stream: true;
  session_id: string;
  provider: string;
  /** T31：仅当用户在本次入口显式切换过模式才发送；否则服务端以会话 durable 为准。 */
  permission_mode?: string;
  /** T31：仅当 /mode 被显式调用过才发送；否则服务端以会话 durable 为准。 */
  agent_mode?: string;
  /** T31：客户端只发 workspace id/路径，服务端解析权威路径（workspace SSOT）。 */
  workspace?: string;
  messages: { role: string; content: string }[];
  /** T_now 输出精简 / 写代码精简（可省略；由 /output、/code 设置） */
  output_compact?: boolean;
  output_mode?: string;
  code_compact?: boolean;
  code_mode?: string;
};

export async function streamChat(
  baseUrl: string,
  apiKey: string,
  body: ChatBody,
  handlers: SseHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const url = `${baseUrl.replace(/\/$/, "")}/v1/chat/completions`;
  const headers: Record<string, string> = {
    Accept: "text/event-stream",
    "Content-Type": "application/json",
  };
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;

  const res = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status}: ${detail.slice(0, 200)}`);
  }
  if (!res.body) throw new Error("No response body");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let carry = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      carry += decoder.decode(value, { stream: true });
      const parts = carry.split("\n");
      carry = parts.pop() ?? "";
      for (const line of parts) {
        const obj = parseDataLine(line);
        if (!obj) continue;
        const d = deltaText(obj);
        if (d) handlers.onDelta(d);
        const xy = extractXy(obj);
        if (xy) handlers.onXy(xy);
      }
    }
    if (carry.trim()) {
      const obj = parseDataLine(carry);
      if (obj) {
        const d = deltaText(obj);
        if (d) handlers.onDelta(d);
        const xy = extractXy(obj);
        if (xy) handlers.onXy(xy);
      }
    }
    handlers.onDone();
  } catch (err) {
    if ((err as Error).name === "AbortError") {
      handlers.onDone();
      return;
    }
    handlers.onError(err as Error);
  }
}

export async function resolvePermission(
  baseUrl: string,
  apiKey: string,
  requestId: string,
  choice: "allow" | "deny" | "remind",
): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
  await fetch(`${baseUrl.replace(/\/$/, "")}/v1/permission/resolve`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      request_id: requestId,
      approved: choice === "allow",
      outcome: choice,
      actor: "cli-ts",
    }),
  });
}

export async function interruptSession(
  baseUrl: string,
  apiKey: string,
  sessionId: string,
): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
  await fetch(`${baseUrl.replace(/\/$/, "")}/v1/interrupt`, {
    method: "POST",
    headers,
    body: JSON.stringify({ session_id: sessionId }),
  });
}

export type SlashResponse = {
  handled: boolean;
  unknown?: boolean;
  name?: string;
  handler?: string;
  message?: string;
  result?: { message?: string } | null;
};

/** 统一斜杠命令：POST /v1/slash（server 命令）。 */
export async function postSlashCommand(
  baseUrl: string,
  apiKey: string,
  body: Record<string, unknown>,
): Promise<SlashResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
  const res = await fetch(`${baseUrl.replace(/\/$/, "")}/v1/slash`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as SlashResponse;
}

export async function healthOk(baseUrl: string): Promise<boolean> {
  try {
    const res = await fetch(`${baseUrl.replace(/\/$/, "")}/health`, {
      signal: AbortSignal.timeout(2000),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export type SessionInfo = {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
};

export type LoadedMessage = {
  id: string;
  role: "user" | "assistant" | "tool";
  text: string;
  createdAt: number;
  isThought?: boolean;
  toolName?: string;
  toolInput?: string;
  toolStatus?: string;
  mediaRefs?: string[];
};

/** T31：服务端签发新会话 id（消除客户端自造 UUID）。workspace 由服务端解析。 */
export async function createSession(
  baseUrl: string,
  apiKey: string,
  workspace?: string,
): Promise<{ session_id: string; cwd: string }> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
  const res = await fetch(`${baseUrl.replace(/\/$/, "")}/v1/sessions`, {
    method: "POST",
    headers,
    body: JSON.stringify({ workspace: workspace || undefined }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as { session_id: string; cwd: string };
}

/** T31：列出服务端会话（恢复历史入口）。 */
export async function listSessions(
  baseUrl: string,
  apiKey: string,
): Promise<SessionInfo[]> {
  const headers: Record<string, string> = {};
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
  const res = await fetch(`${baseUrl.replace(/\/$/, "")}/v1/sessions`, { headers });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = (await res.json()) as { sessions: SessionInfo[] };
  return data.sessions ?? [];
}

/** T31：按 session_id 读取消息 + 服务端权威 cwd（恢复历史 / /load）。 */
export async function getSessionMessages(
  baseUrl: string,
  apiKey: string,
  sessionId: string,
): Promise<{ session_id: string; cwd: string; messages: LoadedMessage[] }> {
  const headers: Record<string, string> = {};
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
  const res = await fetch(
    `${baseUrl.replace(/\/$/, "")}/v1/sessions/${encodeURIComponent(sessionId)}/messages`,
    { headers },
  );
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as {
    session_id: string;
    cwd: string;
    messages: LoadedMessage[];
  };
}

type AssistantItem = Extract<TimelineItem, { kind: "assistant" }>;
type ToolItem = Extract<TimelineItem, { kind: "tool" }>;

/** 安全的数值解析：非有限数返回 undefined。 */
function fnum(v: unknown): number | undefined {
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

/** usage 事件 → 结构化用量（字段名对齐 GUI core.ts 的 parseSseBlock）。 */
function usageFrom(xy: Record<string, unknown>): UsageInfo {
  return {
    promptTokens: fnum(xy.prompt_tokens) ?? 0,
    completionTokens: fnum(xy.completion_tokens) ?? 0,
    cacheHitTokens: fnum(xy.cache_hit_tokens),
    cacheMissTokens: fnum(xy.cache_miss_tokens),
    cny: fnum(xy.cny),
    contextLimit: fnum(xy.context_limit),
  };
}

/** 归一化 TodoWrite todos 数组为 `{content,status}[]`（对齐 GUI normalizeTodoRows 的宽松解析）。 */
function normalizeTodos(raw: unknown): TodoRow[] {
  if (!Array.isArray(raw)) return [];
  const out: TodoRow[] = [];
  for (const r of raw) {
    if (!r || typeof r !== "object" || Array.isArray(r)) continue;
    const row = r as Record<string, unknown>;
    const content = typeof row.content === "string" ? row.content.trim() : "";
    const status = row.status;
    if (!content) continue;
    if (status === "pending" || status === "in_progress" || status === "completed") {
      out.push({ content, status });
    }
  }
  return out;
}

/** 就地更新最后一条匹配的 assistant 条目；找不到则原样返回。 */
function mapLastAssistant(
  items: TimelineItem[],
  fn: (it: AssistantItem) => AssistantItem,
): TimelineItem[] {
  for (let i = items.length - 1; i >= 0; i--) {
    const it = items[i];
    if (it && it.kind === "assistant") {
      const copy = [...items];
      copy[i] = fn(it);
      return copy;
    }
  }
  return items;
}

/** 就地更新最后一条匹配谓词的 tool 条目；找不到则原样返回。 */
function mapLastTool(
  items: TimelineItem[],
  matches: (it: ToolItem) => boolean,
  fn: (it: ToolItem) => ToolItem,
): TimelineItem[] {
  for (let i = items.length - 1; i >= 0; i--) {
    const it = items[i];
    if (it && it.kind === "tool" && matches(it)) {
      const copy = [...items];
      copy[i] = fn(it);
      return copy;
    }
  }
  return items;
}

/** 将 xy 事件映射为时间线补丁。 */
export function applyXy(
  items: TimelineItem[],
  xy: Record<string, unknown>,
  nextId: () => string,
): TimelineItem[] {
  const kind = String(xy.type ?? "");

  // ---- 模型思考：累加到当前 assistant 条目 ----
  if (kind === "reasoning_delta") {
    const text = typeof xy.text === "string" ? xy.text : "";
    if (!text) return items;
    return mapLastAssistant(items, (it) => ({
      ...it,
      reasoning: (it.reasoning ?? "") + text,
    }));
  }

  // ---- usage：挂到当前 assistant 条目 ----
  if (kind === "usage") {
    return mapLastAssistant(items, (it) => ({ ...it, usage: usageFrom(xy) }));
  }

  // ---- tool_progress：挂到同名 running tool ----
  if (kind === "tool_progress") {
    const name = String(xy.name ?? xy.tool_name ?? "");
    const message =
      typeof xy.message === "string" && xy.message.trim()
        ? xy.message.trim()
        : "";
    if (!name) return items;
    return mapLastTool(items, (it) => it.name === name, (it) =>
      it.status === "running" && message ? { ...it, progress: message } : it,
    );
  }

  // ---- 独立 todos / todo 事件（防御；权威路径为 tool_result.todos）----
  if (kind === "todos" || kind === "todo") {
    const todos = normalizeTodos(xy.todos);
    if (todos.length === 0) return items;
    return mapLastTool(items, (it) => /todo/i.test(it.name), (it) => ({
      ...it,
      todos,
    }));
  }

  if (kind === "tool_call") {
    const name = String(xy.name ?? xy.tool_name ?? "tool");
    const inp = (xy.input ?? xy.tool_input ?? {}) as Record<string, unknown>;
    let summary = "";
    for (const key of ["path", "file_path", "command", "pattern", "query", "url"]) {
      const v = inp[key];
      if (typeof v === "string" && v.trim()) {
        summary = v.trim();
        break;
      }
    }
    return [
      ...items,
      {
        id: nextId(),
        kind: "tool",
        name,
        summary,
        status: "running",
      },
    ];
  }
  if (kind === "tool_result") {
    const name = String(xy.name ?? xy.tool_name ?? "tool");
    const out = String(xy.output ?? "");
    const isError = Boolean(xy.is_error);
    const todos = normalizeTodos(xy.todos);
    const copy = [...items];
    for (let i = copy.length - 1; i >= 0; i--) {
      const it = copy[i];
      if (it && it.kind === "tool" && it.name === name && it.status === "running") {
        copy[i] = {
          ...it,
          status: isError ? "error" : "completed",
          result: out,
          isError,
          ...(todos.length > 0 ? { todos } : {}),
        };
        return copy;
      }
    }
    return [
      ...copy,
      {
        id: nextId(),
        kind: "tool",
        name,
        summary: "",
        status: isError ? "error" : "completed",
        result: out,
        isError,
        ...(todos.length > 0 ? { todos } : {}),
      },
    ];
  }
  if (kind === "stopped") {
    return [...items, { id: nextId(), kind: "system", text: "■ stopped" }];
  }

  // ---- 系统级 note：context 压缩 ----
  if (kind === "context_compression_start" || kind === "context_compression_complete") {
    const phase = kind === "context_compression_start" ? "开始" : "完成";
    return [...items, { id: nextId(), kind: "system", text: `context 压缩${phase}` }];
  }

  // ---- 系统级 note：权限 resolved ----
  if (kind === "permission_resolved") {
    const approved = Boolean(xy.approved);
    const choice = xy.choice != null ? String(xy.choice) : "";
    const reason = String(xy.reason ?? "");
    const label = choice || (approved ? "allow" : "deny");
    return [
      ...items,
      {
        id: nextId(),
        kind: "system",
        text: `permission ${label}${reason ? ` · ${reason}` : ""}`,
      },
    ];
  }

  // ---- 系统级 note：ask ----
  if (kind === "ask_user_pending") {
    const question = String(xy.question ?? "");
    return [
      ...items,
      { id: nextId(), kind: "system", text: question ? `ask · ${question}` : "ask" },
    ];
  }
  if (kind === "ask_user_resolved") {
    const answer = xy.answer != null ? String(xy.answer) : "";
    return [
      ...items,
      { id: nextId(), kind: "system", text: `ask 已答复${answer ? ` · ${answer}` : ""}` },
    ];
  }

  // ---- 系统级 note：plan ----
  if (kind === "plan_pending") {
    const plan = String(xy.plan ?? "");
    return [
      ...items,
      { id: nextId(), kind: "system", text: plan ? `plan 待批准 · ${plan}` : "plan 待批准" },
    ];
  }
  if (kind === "plan_resolved") {
    const approved = Boolean(xy.approved);
    const reason = String(xy.reason ?? "");
    return [
      ...items,
      {
        id: nextId(),
        kind: "system",
        text: `plan ${approved ? "已批准" : "被拒绝"}${reason ? ` · ${reason}` : ""}`,
      },
    ];
  }

  return items;
}
