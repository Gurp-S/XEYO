import type { TimelineItem, TodoRow, UsageInfo } from "../types.js";
import {consumeChatStream} from './consumeChatStream.js';

export type SseHandlers = {
  onDelta: (text: string) => void;
  onXy: (xy: Record<string, unknown>) => void;
  onDone: () => void;
  onError: (err: Error) => void;
  /** 忙时受理（202 JSON，非流式）：queued 位次 / steered 边界投递（与 GUI 同一份口径）。 */
  onAccepted?: (payload: AcceptedPayload) => void;
};

/** 202 受理体（server/stream_contract.accepted_payload 的镜像；键集漂移即幽灵卡）。 */
export type AcceptedPayload = {
  queued?: boolean;
  steered?: boolean;
  /** boundary = 下一采样边界投递；after_turn = settle 后排（下一轮送达）。 */
  delivery?: string;
  queue_id?: string;
  position?: number;
  message_id?: string;
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
  /** 会话语义（忙时提交）：true=忙则入队（202），否则维持 409（旧客户端语义）。 */
  queue_if_busy?: boolean;
  /** 引导：忙时投到本轮下一个采样边界，不打断工具批次（Codex turn/steer 同形）。 */
  steer_if_busy?: boolean;
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
  // 忙时受理是 **JSON（202 受理体），不是流**：queued 位次 / steered 边界投递。
  // 没有这条分支时，受理体会被当 SSE 消费 ⇒ 界面永远等不到 done（幽灵"进行中"）。
  const ctype = res.headers?.get?.("content-type") ?? "";
  if (ctype.includes("application/json")) {
    const payload = (await res.json().catch(() => null)) as AcceptedPayload | null;
    if (payload && handlers.onAccepted) {
      handlers.onAccepted(payload);
      return;
    }
    handlers.onError(
      new Error("服务端受理了忙时提交，但客户端没有对应的回执处理（版本不匹配）"),
    );
    return;
  }
  if (!res.body) throw new Error("No response body");

  await consumeChatStream(res.body, handlers, line => {
    const obj = parseDataLine(line);
    if (!obj) return;
    const d = deltaText(obj);
    if (d) handlers.onDelta(d);
    const xy = extractXy(obj);
    if (xy) handlers.onXy(xy);
  }, signal);
}

/**
 * 决议送达了但**没被接受**：200 信封里的 `{ok:false}`。
 *
 * 这一档和"没送达"（网络/5xx）不是一件事，和"批准成功"更不是。
 * 后端的 reason 有两种（server/routers/control.py::_resolve_miss_reason）：
 * `already_resolved` = 别的表面已经答过；`no_such_request` = 挂起项已经不在
 * （服务重启会清掉内存里的它）。两种都不能写"✓ allowed"。
 */
export class DecisionNotApplied extends Error {
  readonly reason: string;

  constructor(reason: string, detail: string) {
    super(
      detail ||
        (reason === "already_resolved"
          ? "该项已在别处答复（远程或另一次点击）"
          : reason === "no_such_request"
            ? "挂起项已不在服务端（服务重启会清掉它）"
            : "服务端未接受这次决议"),
    );
    this.name = "DecisionNotApplied";
    this.reason = reason;
  }
}

async function envelopeOf(res: Response): Promise<Record<string, unknown> | null> {
  try {
    const body: unknown = await res.json();
    return body && typeof body === "object" && !Array.isArray(body)
      ? (body as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

function notApplied(body: Record<string, unknown> | null): DecisionNotApplied {
  const reason = typeof body?.reason === "string" ? body.reason : "";
  const detail =
    typeof body?.detail === "string"
      ? body.detail
      : typeof body?.message === "string"
        ? body.message
        : "";
  return new DecisionNotApplied(reason, detail);
}

/**
 * 决议未生效后的本地处置：除 already_resolved（别处已答，本端收场）外都保留弹窗。
 * 未送达（网络/5xx）与未被接受（no_such_request 等）都可能重试成功；弹窗被丢
 * 等于收走唯一作答入口，而服务端可能仍在等这单决议（GUI 同款：失败保留面板）。
 */
export function decisionRetainsPrompt(e: unknown): boolean {
  return !(e instanceof DecisionNotApplied && e.reason === "already_resolved");
}

export async function resolvePermission(
  baseUrl: string,
  apiKey: string,
  requestId: string,
  choice: "allow" | "deny" | "remind",
): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
  const res = await fetch(`${baseUrl.replace(/\/$/, "")}/v1/permission/resolve`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      request_id: requestId,
      approved: choice === "allow",
      outcome: choice,
      actor: "tui",
    }),
  });
  // 决议必须确认送达：本文件其余 5 个 helper 都查 res.ok，只有这两个不查，
  // 于是 403/404/422 会被吞掉、界面照常写下 "✓ allowed"。
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  // 但 res.ok 只是 HTTP 层：这个端点在 200 信封里用 {ok:false} 表达"没接受"，
  // 只看状态码会把"别处已经答过 / 挂起项没了"写成 ✓ allowed。
  const body = await envelopeOf(res);
  if (!body || body.ok !== true) throw notApplied(body);
}

export async function resolveAsk(
  baseUrl: string,
  apiKey: string,
  requestId: string,
  answer: string,
): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
  const res = await fetch(`${baseUrl.replace(/\/$/, "")}/v1/ask/resolve`, {
    method: "POST",
    headers,
    body: JSON.stringify({ request_id: requestId, answer, actor: "tui" }),
  });
  // 与 resolvePermission 同规：HTTP 层与 200 信封里的 {ok:false} 是两件事，
  // 只看状态码会把「已在别处答过 / 挂起项已不在」写成 ✓。
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const body = await envelopeOf(res);
  if (!body || body.ok !== true) throw notApplied(body);
}

export async function interruptSession(
  baseUrl: string,
  apiKey: string,
  sessionId: string,
): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
  const res = await fetch(`${baseUrl.replace(/\/$/, "")}/v1/interrupt`, {
    method: "POST",
    headers,
    body: JSON.stringify({ session_id: sessionId }),
  });
  // 同上：本地 abort() 只保证"不再接收"，服务端有没有停要靠这个响应。
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const body = await envelopeOf(res);
  if (!body || body.ok !== true) {
    throw notApplied(
      body ?? { detail: "服务端未确认中断（回执缺少 ok 字段）" },
    );
  }
}

export type SlashResponse = {
  handled: boolean;
  unknown?: boolean;
  name?: string;
  handler?: string;
  message?: string;
  result?: { message?: string } | null;
};

/**
 * 会话端点的 200 回执必须校验形状。这些接口的真失败走 HTTP 状态码，
 * 于是"200 但读不出"过去会被写成一句正面事实：
 * - `sessions` 不在体里 ⇒ /load 说「没有可恢复的会话」（`?? []` 让它看着像事实）；
 * - `session_id` 不在体里 ⇒ 拿 undefined 当会话 id 继续发请求，`--json` 还会把它印进机器契约；
 * - `messages` 不在体里 ⇒ 历史显示成空的；
 * - 服务端一直在返回的 `degraded` / `read_errors` / `skipped_lines` 被整个丢掉 ⇒
 *   一份读坏的 transcript 显示成"完整历史"。
 * 抛错走各调用点已有的 catch（`/load 失败：…`），不改任何签名。
 */
function requireObject(payload: unknown, what: string): Record<string, unknown> {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error(`${what}：回执不是对象，读不出结果`);
  }
  return payload as Record<string, unknown>;
}

/**
 * 非 200 时带上服务端给的原因（统一错误体是 `{detail:{message,type}}`，也见过裸 `{detail}`）。
 * 只报状态码的话，"/load 打错会话 id" 与 "服务没起" 会长成同一句话。
 */
async function httpFailure(res: Response): Promise<Error> {
  let detail = "";
  try {
    const body: unknown = await res.json();
    const o = body && typeof body === "object" && !Array.isArray(body)
      ? (body as Record<string, unknown>)
      : null;
    const d = o?.detail;
    if (typeof d === "string") detail = d;
    else if (d && typeof d === "object" && typeof (d as { message?: unknown }).message === "string") {
      detail = (d as { message: string }).message;
    } else if (typeof o?.message === "string") detail = o.message;
  } catch {
    /* 错误体不是 JSON（反代 / 登录页）：只报状态码，不编原因 */
  }
  return new Error(`HTTP ${res.status}${detail ? ` · ${detail}` : ""}`);
}

export function parseCreatedSession(
  payload: unknown,
): { session_id: string; cwd: string } {
  const o = requireObject(payload, "新建会话");
  if (o.ok !== true) {
    throw new Error("新建会话：服务端没有接受这次申请");
  }
  if (typeof o.session_id !== "string" || !o.session_id.trim()) {
    throw new Error("新建会话：回执里没有服务端签发的 session_id（不能自造一个）");
  }
  if (typeof o.cwd !== "string") {
    throw new Error("新建会话：回执缺 cwd（工作区归属读不出）");
  }
  return { session_id: o.session_id, cwd: o.cwd };
}

export function parseSessionList(payload: unknown): SessionInfo[] {
  const o = requireObject(payload, "会话列表");
  if (!Array.isArray(o.sessions)) {
    throw new Error("会话列表：回执缺 sessions —— 读不出不等于没有可恢复的会话");
  }
  for (const item of o.sessions) {
    if (!item || typeof item !== "object" || typeof (item as SessionInfo).id !== "string" || !(item as SessionInfo).id) {
      throw new Error("会话列表：sessions 里有一条不是会话");
    }
  }
  return o.sessions as SessionInfo[];
}

export function parseSlashResponse(payload: unknown): SlashResponse {
  const o = requireObject(payload, "斜杠命令");
  if (typeof o.handled !== "boolean") {
    throw new Error("斜杠命令：回执缺 handled —— 读不出服务端有没有接这个命令");
  }
  return o as unknown as SlashResponse;
}

/** 载入的会话：`incomplete` 只在服务端说这份 transcript 没读完时出现。 */
export type LoadedSession = {
  session_id: string;
  cwd: string;
  messages: LoadedMessage[];
  incomplete?: string;
};

export function parseLoadedSession(payload: unknown): LoadedSession {
  const o = requireObject(payload, "载入会话历史");
  if (
    typeof o.session_id !== "string" ||
    !o.session_id ||
    !Array.isArray(o.messages) ||
    typeof o.cwd !== "string"
  ) {
    throw new Error("载入会话历史：回执缺 session_id / messages / cwd —— 读不出不等于这个会话没有消息");
  }
  const bits: string[] = [];
  if (o.degraded === true) bits.push("服务端读取降级");
  if (typeof o.skipped_lines === "number" && o.skipped_lines > 0) {
    bits.push(`跳过 ${o.skipped_lines} 行`);
  }
  if (Array.isArray(o.read_errors) && o.read_errors.length > 0) {
    bits.push(`${o.read_errors.length} 处读取失败`);
  }
  return {
    session_id: o.session_id,
    cwd: o.cwd,
    messages: o.messages as LoadedMessage[],
    ...(bits.length > 0 ? { incomplete: bits.join(" · ") } : {}),
  };
}

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
  return parseSlashResponse(await res.json());
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
  if (!res.ok) throw await httpFailure(res);
  return parseCreatedSession(await res.json());
}

/** T31：列出服务端会话（恢复历史入口）。 */
export async function listSessions(
  baseUrl: string,
  apiKey: string,
): Promise<SessionInfo[]> {
  const headers: Record<string, string> = {};
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
  const res = await fetch(`${baseUrl.replace(/\/$/, "")}/v1/sessions`, { headers });
  if (!res.ok) throw await httpFailure(res);
  return parseSessionList(await res.json());
}

/** T31：按 session_id 读取消息 + 服务端权威 cwd（恢复历史 / /load）。 */
export async function getSessionMessages(
  baseUrl: string,
  apiKey: string,
  sessionId: string,
): Promise<LoadedSession> {
  const headers: Record<string, string> = {};
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
  const res = await fetch(
    `${baseUrl.replace(/\/$/, "")}/v1/sessions/${encodeURIComponent(sessionId)}/messages`,
    { headers },
  );
  if (!res.ok) throw await httpFailure(res);
  return parseLoadedSession(await res.json());
}

type AssistantItem = Extract<TimelineItem, { kind: "assistant" }>;
type ToolItem = Extract<TimelineItem, { kind: "tool" }>;

/** 安全的数值解析：非有限数返回 undefined。 */
function fnum(v: unknown): number | undefined {
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

/** usage 事件 → 结构化用量（字段名对齐 GUI core.ts 的 parseSseBlock）。
 *  缺字段留 undefined：把「没有这项账」渲染成 0 会让终端头部谎报消耗。 */
function usageFrom(xy: Record<string, unknown>): UsageInfo {
  return {
    promptTokens: fnum(xy.prompt_tokens),
    completionTokens: fnum(xy.completion_tokens),
    cacheHitTokens: fnum(xy.cache_hit_tokens),
    cacheMissTokens: fnum(xy.cache_miss_tokens),
    // 金额两态必须分开：`cny: null` 是上游核实过的「该厂商没有权威价目」，
    // `fnum` 会把它读成 0（免费），那是反方向的谎报，所以先判 null 再判数值。
    cny: xy.cny == null ? undefined : fnum(xy.cny),
    /** 只有显式 null 才算「已核实无价目」；字段缺席只是这一轮没报金额。 */
    costUnknown: xy.cny === null,
    contextLimit: fnum(xy.context_limit),
  };
}

/** 服务端在 tool_call / tool_result 两边都带 tool_use_id；旧流可能没有。 */
function toolUseIdOf(xy: Record<string, unknown>): string {
  const raw = xy.tool_use_id ?? xy.toolUseId;
  return typeof raw === "string" ? raw : "";
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

/** 该收这条事件/结果的卡片：先按 tool_use_id 认；没有身份时才退回「最早一条
 *  同名且仍在跑」的先进先出猜测——同轮并行同名工具（一次批量读三个文件）按
 *  最后一条匹配会把结果贴到别的卡片上。 */
function findToolIndex(items: TimelineItem[], wantId: string, name: string): number {
  if (wantId) {
    // 身份已知就以此为准：查无此卡时**不许**退回"同名最早在跑"，否则一条对不上号
    // 的结果会把别人的卡结掉（而真正的调用永远停在 running）。
    for (let i = items.length - 1; i >= 0; i--) {
      const it = items[i];
      if (it && it.kind === "tool" && it.toolUseId === wantId) return i;
    }
    return -1;
  }
  for (let i = 0; i < items.length; i++) {
    const it = items[i];
    if (it && it.kind === "tool" && it.name === name && it.status === "running") {
      return i;
    }
  }
  return -1;
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
    if (!name || !message) return items;
    const idx = findToolIndex(items, toolUseIdOf(xy), name);
    if (idx < 0) return items;
    const withProgress = [...items];
    withProgress[idx] = { ...(withProgress[idx] as ToolItem), progress: message };
    return withProgress;
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
    const callId = toolUseIdOf(xy);
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
        ...(callId ? { toolUseId: callId } : {}),
      },
    ];
  }
  if (kind === "tool_result") {
    const name = String(xy.name ?? xy.tool_name ?? "tool");
    const out = String(xy.output ?? "");
    const isError = Boolean(xy.is_error);
    const todos = normalizeTodos(xy.todos);
    const settled = {
      status: isError ? ("error" as const) : ("completed" as const),
      result: out,
      isError,
      ...(todos.length > 0 ? { todos } : {}),
    };
    const idx = findToolIndex(items, toolUseIdOf(xy), name);
    if (idx >= 0) {
      const copy = [...items];
      copy[idx] = { ...(copy[idx] as ToolItem), ...settled };
      return copy;
    }
    return [...items, { id: nextId(), kind: "tool", name, summary: "", ...settled }];
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
