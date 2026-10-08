import {useQueuedTurns} from '../hooks/useQueuedTurns.js';
import {messagesToItems, appendAssistantDelta} from '../lib/queuedTimeline.js';
import {restoreFailedDraft} from '../lib/failedDraft.js';
import { Box, Static, useApp, useInput, useStdout } from "ink";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  applyXy,
  createSession,
  DecisionNotApplied,
  decisionRetainsPrompt,
  getSessionMessages,
  interruptSession,
  listSessions,
  postSlashCommand,
  resolveAsk,
  resolvePermission,
  streamChat,
} from "../api/sse.js";
import { EmptyState } from "../components/EmptyState.js";
import { ErrorBanner } from "../components/ErrorBanner.js";
import { HeaderBar } from "../components/HeaderBar.js";
import { HelpPanel } from "../components/HelpPanel.js";
import { AskModal } from "../components/AskModal.js";
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
import {
  askKeyIntent,
  askReceipt,
  parseAskPending,
  type AskPrompt,
} from "../lib/askPrompt.js";
import {
  acceptedNote,
  busySlashNote,
  resolveBusySubmit,
} from "../lib/busySubmit.js";
import { routeKey } from "../lib/keyRouter.js";
import { isPeerChoicePrompt, parsePermissionPending } from "../lib/permissionPrompt.js";
import { parseSlashInput } from "../lib/slash.js";
import {
  gapNote,
  gapThroughOf,
  lastAssistantText,
  recoverAssistantAfterGap,
} from "../lib/streamGap.js";
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
  const [ask, setAsk] = useState<AskPrompt | null>(null);
  const [askDraft, setAskDraft] = useState("");
  const [showDash, setShowDash] = useState(!initial.demo);
  const [showHelp, setShowHelp] = useState(false);
  const [suggestIndex, setSuggestIndex] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const idRef = useRef(0);
  /** /retry 的数据源：最近一次真实用户消息（命令回显不计）。 */
  const lastUserRef = useRef("");
  /** T31：本次入口是否显式切换过模式（/mode /output /code /approval）。 */
  const modesTouchedRef = useRef(false);
  /** 本回合服务端报过的"缺帧到哪个事件"（0 = 没缺过）。见 onXy 的 stream_gap 分支。 */
  const gapThroughRef = useRef(0);
  const history = useInputHistory();
  const { connected, refresh } = useEngineHealth(config.baseUrl);
  const elapsedSec = useElapsed(busy);

  const nextId = useCallback(() => {
    idRef.current += 1;
    return `i${idRef.current}`;
  }, []);

  function receiveXy(xy: Record<string, unknown>) {
  const gap = gapThroughOf(xy);
  if (gap) {
    // 引擎在这条连接上丢了帧 ⇒ 本地尾巴从此刻起是缺段。不能说"完成"，
    // 也不能当完整正文留下：收尾交给 onDone 回拉 transcript 对账。
    gapThroughRef.current = Math.max(gapThroughRef.current, gap);
    return;
  }
  const kind = String(xy.type ?? "");
  if (kind === "permission_pending") {
    const frame = parsePermissionPending(xy);
    if (frame.kind === "open") {
      setPending(frame.prompt);
      return;
    }
    // 缺 request_id 的帧开不了可决议的弹窗：不写 requestId:"" 去骗过后端，
    // 也不把用户锁在一个按什么都发不出决定的面板上。
    setItems((prev) => [
      ...prev,
      { id: nextId(), kind: "system", text: `${gly.warn} ${frame.detail}` },
    ]);
    return;
  }
  if (kind === "permission_resolved") {
    const rid = String(xy.request_id ?? "").trim();
    // 别处（GUI/微信/超时）已答：本端弹窗随之关掉；一个没人等的弹窗
    // 会把 Esc 变成"打断回合"的陷阱，或把按键引向"已在别处答复"的假流程。
    setPending((cur) =>
      cur && (!rid || cur.requestId === rid) ? null : cur,
    );
  }
  if (kind === "ask_user_pending") {
    // 提问到达 = 打开作答弹窗（#10）；帧缺 request_id 时开不了可决议的弹窗，
    // 交给 applyXy 落一条静态 note（旧行为）。
    const parsed = parseAskPending(xy);
    if (parsed) {
      setAsk(parsed);
      setAskDraft(parsed.defaultAnswer ?? "");
      return;
    }
  }
  if (kind === "ask_user_resolved") {
    setAsk((cur) =>
      cur && (!String(xy.request_id ?? "").trim() ||
      cur.requestId === String(xy.request_id ?? "").trim())
        ? null
        : cur,
    );
    // 不 return：回执 note 仍进时间线（与 permission_resolved 同规）。
  }
  setItems((prev) => applyXy(prev, xy, nextId));
  }

  const followAccepted = useQueuedTurns({config, abortRef, setItems, setBusy,
    onXy: receiveXy, onError: setError, modesTouched: modesTouchedRef.current});

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
      /* 已中止 */
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
        /* 忽略 */
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
    // 先做完本地能确定的事（停接收、收尾时间线），再异步确认服务端。
    // 回执分两段：本地 abort 是事实，"服务端已中断"必须等 POST 成功才敢说。
    void interruptSession(config.baseUrl, config.apiKey, config.sessionId).catch(
      (e: unknown) => {
        setItems((prev) => [
          ...prev,
          {
            id: nextId(),
            kind: "system",
            text: `${gly.warn} 服务端未确认中断：${String(e)}`,
          },
        ]);
      },
    );
    setBusy(false);
    setPending(null);
    setAsk(null);
    setAskDraft("");
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
  }, [busy, config.apiKey, config.baseUrl, config.sessionId, gly.fail, gly.warn, nextId]);

  /** 关闭一个已经没人等的弹窗：流都结束了还没收到 permission_resolved，
   *  再往服务端发决议只会多余地报错；但弹窗留着会把用户锁死在终端里。 */
  const dismissPending = useCallback(() => {
    if (!pending) return;
    const req = pending;
    setPending(null);
    setItems((prev) => [
      ...prev,
      {
        id: nextId(),
        kind: "system",
        text: `${gly.warn} 授权请求已过期（${req.tool}）：本轮已结束，弹窗已关闭`,
      },
    ]);
  }, [gly.warn, nextId, pending]);

  /** 提交提问作答（#10）：送达失败保留弹窗可重试；别处已答走信息档收起。 */
  const submitAsk = useCallback(
    async (cur: AskPrompt, answer: string) => {
      try {
        await resolveAsk(config.baseUrl, config.apiKey, cur.requestId, answer);
      } catch (e) {
        if (e instanceof DecisionNotApplied && e.reason === "already_resolved") {
          setAsk(null);
          setAskDraft("");
          setItems((prev) => [
            ...prev,
            {
              id: nextId(),
              kind: "system",
              text: `${gly.warn} 该提问已在别处答复（超时或桌面端）`,
            },
          ]);
          return;
        }
        // 未送达：弹窗保留供重试，出声不静默（与 PermissionModal 同规）。
        setItems((prev) => [
          ...prev,
          {
            id: nextId(),
            kind: "system",
            text: `${gly.fail} 作答未送达：${String(e)}（弹窗保留，可重试）`,
          },
        ]);
        return;
      }
      setAsk(null);
      setAskDraft("");
      setItems((prev) => [
        ...prev,
        { id: nextId(), kind: "system", text: askReceipt(answer) },
      ]);
    },
    [config.apiKey, config.baseUrl, gly.fail, gly.warn, nextId],
  );

  useInput((inputKey, key) => {
    if (key.ctrl && inputKey.toLowerCase() === 'r' && followAccepted.paused && !busy && !pending && !ask) {
      void followAccepted.resume();
      return;
    }
    const action = routeKey(inputKey, key, {
      busy,
      pending: !!pending,
      askPending: !!ask,
      showHelp,
      hasError: !!error,
      peerChoice: pending ? isPeerChoicePrompt(pending) : false,
    });
    switch (action) {
      case "interrupt":
        interruptTurn();
        return;
      case "dismiss_pending":
        dismissPending();
        return;
      case "dismiss_ask":
        setAsk(null);
        setAskDraft("");
        setItems((prev) => [
          ...prev,
          {
            id: nextId(),
            kind: "system",
            text: `${gly.warn} 未作答已关闭：模型将等待答复或超时`,
          },
        ]);
        return;
      case "pass_to_input": {
        // 选项态提问：数字 1..n 直接提交该项、s 显式跳过（空答案）。
        if (ask && ask.extraQuestions === 0 && ask.options.length > 0) {
          const intent = askKeyIntent(inputKey, ask);
          if (intent.kind === "submit") {
            void submitAsk(ask, intent.value);
          }
        }
        return;
      }
      case "clear_panels":
        setShowHelp(false);
        setError(null);
        return;
      case "exit":
        exit();
        return;
      case "allow":
        void decide("allow");
        return;
      case "remind":
        void decide("remind");
        return;
      case "deny":
        void decide("deny");
        return;
      case "history_older": {
        const line = history.older(input);
        if (line != null) setInput(line);
        return;
      }
      case "history_newer": {
        const line = history.newer(input);
        if (line != null) setInput(line);
        return;
      }
      case "tab_complete": {
        const opts = slashMatches(input);
        if (opts.length > 0) {
          const next = (suggestIndex + 1) % opts.length;
          // 输入与某项完全一致时切到下一项；否则取当前高亮项
          const cur = opts.indexOf(input);
          const pick =
            cur >= 0 ? opts[(cur + 1) % opts.length]! : opts[suggestIndex % opts.length]!;
          setInput(pick);
          setSuggestIndex(next);
        }
        return;
      }
      default:
        return;
    }
  });

  async function decide(choice: "allow" | "deny" | "remind") {
    if (!pending) return;
    const req = pending;
    setPending(null);
    const verb =
      choice === "allow" ? "allowed" : choice === "remind" ? "remind" : "denied";
    try {
      await resolvePermission(config.baseUrl, config.apiKey, req.requestId, choice);
    } catch (e) {
      // 两种"没生效"要分开说：未送达（网络/5xx）与送达了但没被接受（200 + ok:false）。
      // 后者里 already_resolved 表示别处已经答过 —— 那不是本端的批准，也不能写 ✓。
      const alreadyElsewhere =
        e instanceof DecisionNotApplied && e.reason === "already_resolved";
      // 可重试的失败把弹窗放回去：此前一律丢弃，唯一作答入口消失、
      // 而服务端可能仍在等这单决议（GUI 同款：失败保留面板供重试）。
      if (decisionRetainsPrompt(e)) {
        setPending(req);
      }
      setItems((prev) => [
        ...prev,
        {
          id: nextId(),
          kind: "system",
          text: alreadyElsewhere
            ? `${gly.warn} 该项已在别处答复，本端未做决议（${req.tool}）`
            : `${gly.fail} 决议未被接受（${req.tool} / ${verb}）：${String(e)}`,
        },
      ]);
      setError(String(e));
      return;
    }
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
  }

  async function submit(raw: string) {
    const text = raw.trim();
    if (!text) return;
    if (busy) {
      // 忙时输入面不消失（#2）：非命令文本走服务端队列，命令按 manifest 的
      // when 分流——/stop 等 always 档照常可执行，其余给拒绝指引。
      await submitWhileBusy(text);
      return;
    }
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

  /** 忙时提交：命令按 when 分流；普通文本入队（202 queued），失败回填草稿。 */
  async function submitWhileBusy(text: string) {
    if (text === "/exit" || text === "/quit" || text === "/q") {
      exit();
      return;
    }
    if (text.startsWith("/")) {
      const slash = parseSlashInput(text);
      setItems((prev) => [
        ...prev,
        { id: nextId(), kind: "user" as const, text },
      ]);
      if (slash.command && slash.command.when === "always") {
        await runSlashCommand(slash, text);
        return;
      }
      const name = slash.command?.name ?? slash.name;
      setItems((prev) => [
        ...prev,
        {
          id: nextId(),
          kind: "system" as const,
          text: slash.command
            ? busySlashNote(name)
            : `未知命令 /${name}，试试 /help`,
        },
      ]);
      return;
    }
    setInput("");
    setError(null);
    history.push(text);
    history.resetNav();
    const ok = await sendTurn(text, "busy");
    if (!ok) {
      setInput(current => restoreFailedDraft(current, text));
    }
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
    lastUserRef.current = "";
    setPending(null); setAsk(null); setAskDraft("");
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
      setConfig((c) => ({
        ...c,
        sessionId: data.session_id,
        cwd: data.cwd || c.cwd,
      }));
      lastUserRef.current = "";
      setPending(null); setAsk(null); setAskDraft("");
      const rows = messagesToItems(data.messages);
      setItems(rows);
      setFreezeAt(rows.length);
      // 服务端一直在报这份 transcript 有没有读完（degraded / skipped_lines / read_errors）；
      // 不说出来，一份读坏的历史就会被当成完整历史继续往下写。
      sysNote(
        `已载入会话 ${data.session_id}（工作区：${data.cwd || "(未绑定)"}）` +
          (data.incomplete ? ` · 历史不完整：${data.incomplete}` : ""),
      );
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
        sys("XEYO TUI-TS（Node/Ink）· 引擎由 Python 侧提供");
        return;
      case "docs":
        sys("文档见仓库 docs/ 目录（架构图与评测结果）。");
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

  /**
   * 一轮发送。intent="busy"（#2 忙时提交）：本端已有回合在跑——不预占 busy/abort
   * 语义、不预建气泡；服务端回 202 受理体（queued/steered）时只上用户气泡+回执；
   * 竞态里原回合已结束、服务端真起流（onDelta/onXy 先到）时惰性接管为普通回合。
   * 返回：受理或接管=true（调用方清草稿）；失败=false（调用方回填草稿）。
   */
  async function sendTurn(
    text: string,
    intent: "idle" | "busy" = "idle",
  ): Promise<boolean> {
    const busyIntent = intent === "busy";
    if (!busyIntent) {
      setShowDash(false);
      setFreezeAt(items.length);
      setBusy(true);
    }
    const ac = new AbortController();
    if (!busyIntent) {
      abortRef.current = ac;
    }

    const live = await refresh();
    if (!live) {
      if (!busyIntent) {
        if (abortRef.current === ac) abortRef.current = null;
        setBusy(false);
      }
      setError(
        `Cannot reach ${config.baseUrl}. The Python engine is not running.`,
      );
      // 未上屏的输入不是"已发出的消息"：草稿放回输入框，别让用户重打
      // （与 GUI 的「气泡或草稿必存其一」同规）。
      setInput(current => restoreFailedDraft(current, text));
      return false;
    }

    let surfaced = false;
    let userAdded = false;
    let tookOver = false;
    let accepted = false;
    let assistantId = "";
    const userId = nextId();
    /** 惰性建气泡：idle 在开流前调用；busy 只在真流到达（竞态）时接管为普通回合。 */
    const ensureBubbles = () => {
      if (userAdded) return;
      userAdded = true;
      surfaced = true;
      if (busyIntent && !tookOver) {
        tookOver = true;
        setShowDash(false);
        setFreezeAt(items.length);
        setBusy(true);
        abortRef.current = ac;
      }
      lastUserRef.current = text;
      gapThroughRef.current = 0;
      assistantId = nextId();
      const aid = assistantId;
      setItems((prev) => [
        ...prev,
        { id: userId, kind: "user", text },
        { id: aid, kind: "assistant", text: "", streaming: true },
      ]);
    };

    // T31：会话 id 由服务端签发（无则先申请；不再客户端自造 UUID）。
    // 申请失败与流式失败共用一道守卫：未上屏 ⇒ 放回草稿；已上屏 ⇒ 气泡在，草稿不回。
    // 此前 ensureSessionId 的拒绝会逃出 sendTurn（TextInput 不接 promise）⇒
    // unhandledRejection 处理器直接 process.exit(1)：首次发送时后端一抖 TUI 整个退出。
    try {
      const sessionId = await ensureSessionId();
      if (!busyIntent) {
        ensureBubbles();
      }
      const body: Parameters<typeof streamChat>[2] = {
        model: config.model || "deepseek-chat",
        stream: true,
        session_id: sessionId,
        provider: config.provider,
        workspace: config.cwd,
        messages: [{ role: "user", content: text, id: userId }],
      };
      if (busyIntent) {
        // Enter=排队（202 queued）；Ctrl+Enter=边界引导暂无 TUI 键位入口，
        // 判定纯函数按 modifier=false 调用（键位接上时传真实 modifier 即可）。
        const plan = resolveBusySubmit(false);
        body.queue_if_busy = plan.queueIfBusy;
        body.steer_if_busy = plan.steerIfBusy;
      }
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
          onDelta: (chunk: string, messageId?: string) => {
            ensureBubbles();
            const previousId = assistantId;
            assistantId = messageId || assistantId;
            const id = assistantId;
            setItems(prev => appendAssistantDelta(prev, id, chunk, previousId));
          },
          onXy: (xy: Record<string, unknown>) => {
            ensureBubbles();
            receiveXy(xy);
          },
          onAccepted: (payload) => {
            // 忙时受理（202）：不是一轮对话——用户气泡 + 中性回执（含位次/口径）。
            accepted = true;
            surfaced = true;
            const noteId = nextId();
            const id = payload.message_id || userId;
            setItems(prev => [
              ...prev.filter(item => item.id !== userId && !(item.kind === 'assistant' && item.id === assistantId && !item.text)),
              {id, kind: 'user', text},
              {id: noteId, kind: 'system', text: acceptedNote(payload)},
            ]);
            followAccepted.accept(payload, id, noteId);
          },
          onDone: () => {
            if (accepted || !userAdded) {
              return;
            }
            const gapThrough = gapThroughRef.current;
            gapThroughRef.current = 0;
            const settle = (text?: string) =>
              setItems((prev) =>
                prev.map((it) =>
                  it.id === assistantId && it.kind === "assistant"
                    ? {
                        ...it,
                        streaming: false,
                        ...(text == null ? null : { text }),
                      }
                    : it,
                ),
              );
            if (!gapThrough) {
              settle();
              return;
            }
            // 缺过帧 ⇒ 正文以服务端 transcript 为准（引擎完整落盘，丢的只是这一次投递）；
            // 拉不到或拉失败都必须出声，绝不把缺段当完整内容留下。
            void recoverAssistantAfterGap({
              gapThrough,
              loadText: async () =>
                lastAssistantText(
                  messagesToItems(
                    (await getSessionMessages(config.baseUrl, config.apiKey, sessionId))
                      .messages,
                  ),
                ),
            })
              .then(({ text, note }) => {
                settle(text ?? undefined);
                sysNote(note);
              })
              .catch(() => {
                settle();
                sysNote(gapNote(gapThrough, "failed"));
              });
          },
          onError: (err: Error) => setError(err.message),
        },
        ac.signal,
      );
    } catch (e) {
      if (!surfaced) {
        setInput(current => restoreFailedDraft(current, text));
      }
      setError(String(e));
      return false;
    } finally {
      // busy 提交未接管（受理/失败）时不碰 busy/abort——原回合还在跑。
      if ((!busyIntent || tookOver) && abortRef.current === ac) {
        abortRef.current = null;
        setBusy(false);
      }
      void refresh();
    }
    return accepted || tookOver;
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
      {ask ? (
        <AskModal
          prompt={ask}
          draft={askDraft}
          onDraftChange={setAskDraft}
          onSubmitText={(v) => void submitAsk(ask, v)}
        />
      ) : null}
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
          disabled={Boolean(pending) || Boolean(ask)}
          connected={connected}
          elapsedSec={elapsedSec}
          suggestIndex={suggestIndex}
          hint={
            streamingAssistant
              ? `esc to interrupt · ${elapsedSec}s`
              : followAccepted.paused ? '队列已暂停 · Ctrl+R 继续投递' : undefined
          }
        />
      ) : null}
    </Box>
  );
}
