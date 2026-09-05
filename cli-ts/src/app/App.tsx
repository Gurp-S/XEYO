import { Box, Static, useApp, useInput, useStdout } from "ink";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  applyXy,
  createSession,
  getSessionMessages,
  interruptSession,
  listSessions,
  postSlashCommand,
  resolvePermission,
  streamChat,
  type LoadedMessage,
} from "../api/sse.js";
import { EmptyState } from "../components/EmptyState.js";
import { ErrorBanner } from "../components/ErrorBanner.js";
import { HeaderBar } from "../components/HeaderBar.js";
import { HelpPanel } from "../components/HelpPanel.js";
import { PermissionModal } from "../components/PermissionModal.js";
import { PromptLine, slashMatches } from "../components/PromptLine.js";
import {
  TimelineItemView,
  withTurnMeta,
} from "../components/TimelineItemView.js";
import { TinyFallback } from "../components/TinyFallback.js";
import { WelcomeDash } from "../components/WelcomeDash.js";
import { runDemoTurn } from "../demo.js";
import { useElapsed } from "../hooks/useElapsed.js";
import { useEngineHealth } from "../hooks/useEngineHealth.js";
import { useInputHistory } from "../hooks/useInputHistory.js";
import { parseSlashInput } from "../lib/slash.js";
import { g } from "../theme.js";
import type { CliConfig, PermissionPrompt, TimelineItem } from "../types.js";

type Props = { config: CliConfig };

function shouldCompactTool(
  items: TimelineItem[],
  index: number,
  frozen: boolean,
): boolean {
  const it = items[index];
  if (!it || it.kind !== "tool") return false;
  if (it.status === "running") return false;
  if (frozen) return true;
  for (let j = index + 1; j < items.length; j++) {
    const n = items[j];
    if (n && (n.kind === "tool" || n.kind === "assistant")) return true;
  }
  return false;
}

/** T31：把服务端恢复的消息（/v1/sessions/{id}/messages 形状）映射为时间线条目。 */
function messagesToItems(msgs: LoadedMessage[]): TimelineItem[] {
  const out: TimelineItem[] = [];
  for (const m of msgs) {
    if (m.role === "user") {
      out.push({ id: m.id, kind: "user", text: m.text });
    } else if (m.role === "assistant") {
      out.push({ id: m.id, kind: "assistant", text: m.text });
    } else if (m.role === "tool") {
      const isError = m.toolStatus === "error";
      out.push({
        id: m.id,
        kind: "tool",
        name: m.toolName || "tool",
        summary: m.toolInput || "",
        status: isError ? "error" : "completed",
        result: m.text,
        isError,
      });
    }
  }
  return out;
}

export function App({ config: initial }: Props) {
  const { exit } = useApp();
  const { stdout } = useStdout();
  const cols = stdout?.columns ?? 80;
  const gly = g();
  const [config, setConfig] = useState({ ...initial, demo: false });
  const [items, setItems] = useState<TimelineItem[]>([]);
  const [freezeAt, setFreezeAt] = useState(0);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<PermissionPrompt | null>(null);
  const [showDash, setShowDash] = useState(!initial.demo);
  const [showHelp, setShowHelp] = useState(false);
  const [suggestIndex, setSuggestIndex] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const idRef = useRef(0);
  /** /retry 的数据源：最近一次真实用户消息（命令回显不计）。 */
  const lastUserRef = useRef("");
  /** T31：本次入口是否显式切换过模式（/mode /output /code /approval）。 */
  const modesTouchedRef = useRef(false);
  const history = useInputHistory();
  const { connected, refresh } = useEngineHealth(config.baseUrl);
  const elapsedSec = useElapsed(busy);

  const nextId = useCallback(() => {
    idRef.current += 1;
    return `i${idRef.current}`;
  }, []);

  const turnCount = useMemo(
    () => items.filter((i) => i.kind === "user").length,
    [items],
  );

  const frozenItems = useMemo(() => items.slice(0, freezeAt), [items, freezeAt]);
  const liveItems = useMemo(() => items.slice(freezeAt), [items, freezeAt]);
  const frozenMeta = useMemo(() => withTurnMeta(frozenItems), [frozenItems]);
  const liveMeta = useMemo(() => {
    const priorTurns = frozenItems.filter((i) => i.kind === "user").length;
    return withTurnMeta(liveItems).map((row) =>
      row.turnIndex != null
        ? {
            ...row,
            turnIndex: row.turnIndex + priorTurns,
            showTurnDivider: row.turnIndex + priorTurns > 1,
          }
        : row,
    );
  }, [liveItems, frozenItems]);

  const playDemo = useCallback(async () => {
    setShowDash(false);
    setShowHelp(false);
    setError(null);
    setFreezeAt(0);
    setBusy(true);
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      await runDemoTurn(setItems, ac.signal);
      setItems((prev) => [
        ...prev,
        {
          id: nextId(),
          kind: "system",
          text: "demo ended · next message uses the live engine",
        },
      ]);
    } catch {
      /* aborted */
    } finally {
      setBusy(false);
    }
  }, [nextId]);

  useEffect(() => {
    if (!initial.demo) return;
    void playDemo();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const restore = () => {
      try {
        if (process.stdin.isTTY) process.stdin.setRawMode?.(false);
      } catch {
        /* ignore */
      }
      process.stdout.write("\x1b[?25h");
    };
    process.on("exit", restore);
    return () => {
      process.off("exit", restore);
    };
  }, []);

  const streamingAssistant = useMemo(() => {
    for (let i = items.length - 1; i >= 0; i--) {
      const it = items[i];
      if (it?.kind === "assistant" && it.streaming) return it;
    }
    return null;
  }, [items]);

  const interruptTurn = useCallback(() => {
    if (!busy) return;
    abortRef.current?.abort();
    void interruptSession(config.baseUrl, config.apiKey, config.sessionId);
    setBusy(false);
    setPending(null);
    setItems((prev) => [
      ...prev.map((it) =>
        it.kind === "assistant" && it.streaming
          ? { ...it, streaming: false }
          : it.kind === "tool" && it.status === "running"
            ? {
                ...it,
                status: "error" as const,
                isError: true,
                result: "interrupted",
              }
            : it,
      ),
      { id: nextId(), kind: "system", text: `${gly.fail} interrupted` },
    ]);
  }, [busy, config.apiKey, config.baseUrl, config.sessionId, gly.fail, nextId]);

  useInput((inputKey, key) => {
    if (pending) {
      const c = inputKey.toLowerCase();
      if (c === "a" || c === "y") void decide("allow");
      else if (c === "r") void decide("remind");
      else if (c === "d" || c === "n") void decide("deny");
      return;
    }

    if (key.escape) {
      if (busy) {
        interruptTurn();
        return;
      }
      if (showHelp || error) {
        setShowHelp(false);
        setError(null);
        return;
      }
    }

    if (!busy && !pending) {
      if (key.upArrow) {
        const line = history.older(input);
        if (line != null) setInput(line);
        return;
      }
      if (key.downArrow) {
        const line = history.newer(input);
        if (line != null) setInput(line);
        return;
      }
      if (key.tab) {
        const opts = slashMatches(input);
        if (opts.length > 0) {
          const next = (suggestIndex + 1) % opts.length;
          // when value exactly matches one option, cycle to next; else pick current hi
          const cur = opts.indexOf(input);
          const pick =
            cur >= 0 ? opts[(cur + 1) % opts.length]! : opts[suggestIndex % opts.length]!;
          setInput(pick);
          setSuggestIndex(next);
        }
        return;
      }
    }

    if (key.ctrl && inputKey === "c") {
      if (busy) interruptTurn();
      else exit();
    }
  });

  async function decide(choice: "allow" | "deny" | "remind") {
    if (!pending) return;
    const req = pending;
    setPending(null);
    const label =
      choice === "allow"
        ? `${gly.ok} allowed ${req.tool}`
        : choice === "remind"
          ? `${gly.warn} remind ${req.tool}`
          : `${gly.fail} denied ${req.tool}`;
    setItems((prev) => [
      ...prev,
      { id: nextId(), kind: "system", text: label },
    ]);
    try {
      await resolvePermission(config.baseUrl, config.apiKey, req.requestId, choice);
    } catch (e) {
      setError(String(e));
    }
  }

  async function submit(raw: string) {
    const text = raw.trim();
    if (!text || busy) return;
    setInput("");
    setError(null);
    setShowHelp(false);
    setSuggestIndex(0);
    history.push(text);
    history.resetNav();

    if (text === "/exit" || text === "/quit" || text === "/q") {
      exit();
      return;
    }
    if (text === "/help" || text === "/h" || text === "/?" || text === "?") {
      setShowHelp((v) => !v);
      setShowDash(false);
      return;
    }
    if (text === "/clear") {
      await clearSession();
      return;
    }

    // 统一斜杠命令：/ 前缀 = 命令意图（manifest 驱动）；未知报错，不进模型。
    const slash = parseSlashInput(text);
    if (slash.isSlash) {
      setShowDash(false);
      setShowHelp(false);
      setItems((prev) => [
        ...prev,
        { id: nextId(), kind: "user" as const, text },
      ]);
      await runSlashCommand(slash, text);
      return;
    }

    await sendTurn(text);
  }

  async function newServerSession(): Promise<string> {
    // T31：会话 id 由服务端签发（消除客户端自造 UUID）。
    const created = await createSession(config.baseUrl, config.apiKey, config.cwd);
    setConfig((c) => ({
      ...c,
      sessionId: created.session_id,
      cwd: created.cwd || c.cwd,
    }));
    return created.session_id;
  }

  async function ensureSessionId(): Promise<string> {
    if (config.sessionId) return config.sessionId;
    return newServerSession();
  }

  async function clearSession() {
    setItems([]);
    setFreezeAt(0);
    setShowDash(true);
    setShowHelp(false);
    setError(null);
    try {
      await newServerSession();
    } catch {
      setConfig((c) => ({ ...c, sessionId: "" }));
      sysNote("（未能向服务端申请新会话 id，首次发送时将重试）");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }

  function sysNote(text: string) {
    setItems((prev) => [...prev, { id: nextId(), kind: "system" as const, text }]);
  }

  async function loadSessionById(sid: string) {
    setShowDash(false);
    setShowHelp(false);
    setError(null);
    try {
      const data = await getSessionMessages(config.baseUrl, config.apiKey, sid);
      if (!data.session_id) {
        sysNote(`未找到会话 ${sid}`);
        return;
      }
      setConfig((c) => ({
        ...c,
        sessionId: data.session_id,
        cwd: data.cwd || c.cwd,
      }));
      const rows = messagesToItems(data.messages);
      setItems(rows);
      setFreezeAt(rows.length);
      sysNote(`已载入会话 ${data.session_id}（工作区：${data.cwd || "(未绑定)"}）`);
    } catch (e) {
      sysNote(`/load 失败：${e instanceof Error ? e.message : String(e)}`);
    }
  }

  async function runSlashCommand(
    slash: ReturnType<typeof parseSlashInput>,
    rawLine: string,
  ) {
    const sys = (t: string) =>
      setItems((prev) => [...prev, { id: nextId(), kind: "system" as const, text: t }]);
    if (slash.unknown || !slash.command) {
      sys(`未知命令 /${slash.name}，试试 /help`);
      return;
    }
    const arg = slash.arg.trim();
    switch (slash.command.name) {
      case "demo":
        await playDemo();
        return;
      case "mode": {
        const m = arg.toLowerCase();
        if (m !== "agent" && m !== "plan" && m !== "ask") {
          sys("用法：/mode <agent|plan|ask>");
          return;
        }
        modesTouchedRef.current = true;
        setConfig((c) => ({ ...c, agentMode: m }));
        sys(`mode → ${m}`);
        return;
      }
      case "retry": {
        const last = lastUserRef.current;
        if (!last) {
          sys("还没有可重试的消息");
          return;
        }
        lastUserRef.current = "";
        await sendTurn(last);
        return;
      }
      case "run": {
        if (!arg) {
          sys("用法：/run <command>");
          return;
        }
        await sendTurn(
          "[slash:/run] 请用 Bash 工具执行以下命令并汇总结果（遵守权限门禁，不要执行无关命令）：\n\n" +
            arg,
        );
        return;
      }
      case "output":
      case "code": {
        const lvl = arg.toLowerCase();
        const on = lvl !== "off" && lvl !== "关";
        const mode = ["lite", "full", "ultra"].includes(lvl) ? lvl : "lite";
        modesTouchedRef.current = true;
        setConfig((c) =>
          slash.command!.name === "output"
            ? { ...c, outputCompact: on, outputMode: mode }
            : { ...c, codeCompact: on, codeMode: mode },
        );
        sys(
          `${slash.command!.name === "output" ? "输出精简" : "写代码精简"} ` +
            `${on ? `on（${mode}）` : "off"}（下一轮生效）`,
        );
        return;
      }
      case "approval": {
        const m = arg.toLowerCase();
        if (!["always", "risk", "never"].includes(m)) {
          sys("用法：/approval <always|risk|never>");
          return;
        }
        modesTouchedRef.current = true;
        setConfig((c) => ({ ...c, permissionMode: m }));
        sys(`审批模式 → ${m}（下一轮生效）`);
        return;
      }
      case "model": {
        if (!arg) {
          sys("用法：/model <model_id>");
          return;
        }
        setConfig((c) => ({ ...c, model: arg }));
        sys(`model → ${arg}（下一轮生效）`);
        return;
      }
      case "version":
        sys("XEYO CLI-TS（Node/Ink）· 引擎由 Python 侧提供");
        return;
      case "docs":
        sys("文档见仓库 docs/ 目录（docs/README.md 有索引）。");
        return;
      case "load": {
        if (!arg) {
          try {
            const sessions = await listSessions(config.baseUrl, config.apiKey);
            if (!sessions.length) {
              sys("没有可恢复的会话。");
              return;
            }
            sys("可恢复会话（用法：/load <session_id>）：");
            for (const s of sessions.slice(0, 12)) {
              sys(`  ${s.id}  ${s.title || "(无标题)"}`);
            }
            return;
          } catch (e) {
            sys(`/load 失败：${e instanceof Error ? e.message : String(e)}`);
            return;
          }
        }
        await loadSessionById(arg);
        return;
      }
      default: {
        if (slash.command.handler !== "server") {
          sys(`/${slash.command.name} 暂未实现。`);
          return;
        }
        try {
          const sid = await ensureSessionId();
          const data = await postSlashCommand(config.baseUrl, config.apiKey, {
            name: slash.command.name,
            arg,
            session_id: sid,
            workspace: config.cwd,
            provider: config.provider,
            model: config.model || undefined,
          });
          const out =
            data.result && typeof data.result.message === "string"
              ? data.result.message
              : (data.message ?? "");
          if (out) sys(out);
        } catch (e) {
          sys(
            `/${slash.command.name} 执行失败：${
              e instanceof Error ? e.message : String(e)
            }`,
          );
        }
        return;
      }
    }
  }

  async function sendTurn(text: string) {
    setShowDash(false);
    setFreezeAt(items.length);
    setBusy(true);
    const ac = new AbortController();
    abortRef.current = ac;

    const live = await refresh();
    if (!live) {
      setBusy(false);
      setError(
        `Cannot reach ${config.baseUrl}. The Python engine is not running.`,
      );
      return;
    }

    // T31：会话 id 由服务端签发（无则先申请；不再客户端自造 UUID）。
    const sessionId = await ensureSessionId();

    lastUserRef.current = text;
    setItems((prev) => [...prev, { id: nextId(), kind: "user", text }]);
    const assistantId = nextId();
    setItems((prev) => [
      ...prev,
      { id: assistantId, kind: "assistant", text: "", streaming: true },
    ]);

    try {
      const body: Parameters<typeof streamChat>[2] = {
        model: config.model || "deepseek-chat",
        stream: true,
        session_id: sessionId,
        provider: config.provider,
        workspace: config.cwd,
        messages: [{ role: "user", content: text }],
      };
      // T31：仅当用户显式切换过模式才发送，避免默认值在恢复会话时碾压 durable 记录。
      if (modesTouchedRef.current) {
        body.permission_mode = config.permissionMode;
        body.agent_mode = config.agentMode;
        body.output_compact = config.outputCompact;
        body.output_mode = config.outputMode;
        body.code_compact = config.codeCompact;
        body.code_mode = config.codeMode;
      }
      await streamChat(
        config.baseUrl,
        config.apiKey,
        body,
        {
          onDelta: (chunk: string) => {
            setItems((prev) =>
              prev.map((it) =>
                it.id === assistantId && it.kind === "assistant"
                  ? { ...it, text: it.text + chunk, streaming: true }
                  : it,
              ),
            );
          },
          onXy: (xy: Record<string, unknown>) => {
            const kind = String(xy.type ?? "");
            if (kind === "permission_pending") {
              setPending({
                requestId: String(xy.request_id ?? ""),
                tool: String(xy.tool_name ?? ""),
                prompt: String(xy.prompt ?? xy.reason ?? ""),
              });
              return;
            }
            setItems((prev) => applyXy(prev, xy, nextId));
          },
          onDone: () => {
            setItems((prev) =>
              prev.map((it) =>
                it.id === assistantId && it.kind === "assistant"
                  ? { ...it, streaming: false }
                  : it,
              ),
            );
          },
          onError: (err: Error) => setError(err.message),
        },
        ac.signal,
      );
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
      void refresh();
    }
  }

  const showEmpty =
    !showDash && !showHelp && items.length === 0 && !busy && !error;

  return (
    <Box flexDirection="column" paddingX={0}>
      <TinyFallback cols={cols} />

      {showDash ? (
        <WelcomeDash config={config} connected={connected} />
      ) : (
        <HeaderBar
          config={config}
          connected={connected}
          busy={busy}
          turnCount={turnCount}
          elapsedSec={elapsedSec}
        />
      )}

      {showHelp ? <HelpPanel /> : null}

      <Static items={frozenMeta}>
        {(row, index) => (
          <TimelineItemView
            key={frozenItems[index]?.id ?? `f${index}`}
            item={row.item}
            compactTools={shouldCompactTool(frozenItems, index, true)}
            turnIndex={row.turnIndex}
            showTurnDivider={row.showTurnDivider}
          />
        )}
      </Static>

      {liveMeta.map((row, index) => (
        <TimelineItemView
          key={liveItems[index]?.id ?? `l${index}`}
          item={row.item}
          compactTools={shouldCompactTool(liveItems, index, false)}
          turnIndex={row.turnIndex}
          showTurnDivider={row.showTurnDivider}
        />
      ))}

      {showEmpty ? <EmptyState connected={connected} /> : null}

      {pending ? <PermissionModal pending={pending} /> : null}
      {error ? <ErrorBanner message={error} /> : null}

      {!pending ? (
        <PromptLine
          value={input}
          onChange={(v) => {
            setInput(v);
            setSuggestIndex(0);
            history.resetNav();
            if (error) setError(null);
          }}
          onSubmit={submit}
          mode={config.agentMode}
          busy={busy}
          connected={connected}
          elapsedSec={elapsedSec}
          suggestIndex={suggestIndex}
          hint={
            streamingAssistant
              ? `esc to interrupt · ${elapsedSec}s`
              : undefined
          }
        />
      ) : null}
    </Box>
  );
}
