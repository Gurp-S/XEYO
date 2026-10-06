"""StateSourceAdapter —— V2 的事实可以来自不同权威，但生命周期只有一套规则。

四档 `authority` 决定的是"**谁有资格让这条事实退场**"，不是渲染措辞：

- ``AUTHORITATIVE`` 运行时状态件直接持有（TodoStore / GoalStore）⇒ 它的指令可以直接 SUPERSEDE/RESOLVE。
  本轮**没有实现**这一档的适配器：离线语料里拿不到运行时 store，硬写一个读不到的源就是空壳。
- ``DERIVED`` 确定性推导层从转录算出来（本模块的文件观测、V1 的约束抽取器）⇒ 只有出现新证据才退场。
- ``LITERAL`` 事件原文（reducer 现在产出的全部）⇒ 保守 KEEP。
- ``UNKNOWN`` 生命周期判不出来 ⇒ **必须渲染，永不静默丢弃**（丢掉判不出寿命的东西不是保守，是赌博）。

为什么文件观测要在这里重算而不是直接调 V1 的 `build_file_states`：那条路要扫全量消息，
V2 的"每枪增量 µs 级"当场作废。所以这里用 V1 的**同一批判据原语**
（`classify_tool` / `is_full_file_read` / `read_range` / `content_hash` / `tool_result_text`）
按事件增量地算，再拿 V1 的 `build_file_states` 当**对账金标**（`v1_file_oracle`）。
语义一致、成本不同，才是"复用 V1 的语义"而不是"重造一个更薄的"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .events import KIND_TOOL_RESULT, KIND_TOOL_USE, KIND_USER_TEXT, Event, fingerprint
from .state import (AUTHORITATIVE, DERIVED, LITERAL, RESOLVED, SUPERSEDED, UNKNOWN,
                    AUTHORITY_TIERS, Observation)

__all__ = ["AUTHORITATIVE", "DERIVED", "LITERAL", "UNKNOWN", "AUTHORITY_TIERS",
           "Observation", "Signal", "FileObserver", "constraint_signals",
           "v1_file_oracle", "PRECISE_READ_TOOLS", "error_sig",
           "decision_signals", "attach_decisions", "retire_decisions", "path_touches"]

#: V1 里"精确读"的判定（只有这两种工具能给出 offset/limit 区间，也才配当 hash 的源）
PRECISE_READ_TOOLS = ("Read", "NotebookRead")


@dataclass(frozen=True)
class Signal:
    """适配器 → reducer 的最小单位。`authority` 决定 reducer 能拿它做什么。"""

    kind: str
    key: str
    value: Mapping[str, Any]
    authority: str
    evidence: str
    provenance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.authority not in AUTHORITY_TIERS:
            raise ValueError(f"unknown authority tier: {self.authority}")


@dataclass
class _PathTrack:
    """`FileObserver` 的每路径内部账（增量维护，避免每次全量扫写记录）。"""

    last_obs_idx: int = -1
    hash_src_idx: int = -1
    hash_text: str = ""
    precise_ranges: list[tuple[int, int]] = field(default_factory=list)
    writes: list[tuple[int, str]] = field(default_factory=list)
    observed_ever: bool = False


def _merge_ranges(ranges: set[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    merged: list[tuple[int, int]] = []
    for s, e in sorted(ranges):
        if merged and s <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return tuple(merged)


class FileObserver:
    """事件流 → 路径级读/写观测。单事件成本与该事件有关，与历史长度无关。

    与 V1 `filestate.collect_reads_writes` 逐条对齐的五个决定（都是为了对账能对上，
    不是本地偏好）：① 片段型命令（grep/rg/head/sed/ls）不算观测，只有精确读和整文件读算；
    ② hash 与区间只取**精确读**（`Read` 系），过期时钟取最后一次**有效观测**；
    ③ 一条消息里只有第一个 tool_result 是观测；④ 从没被读过的路径不算 stale；
    ⑤ 写锚在**回执行**而不是调用行。
    """

    def __init__(self) -> None:
        self._tracks: dict[str, _PathTrack] = {}
        self._pend: dict[str, tuple[str, Mapping[str, Any], tuple[str, ...], bool]] = {}
        self._pend_write: dict[str, tuple[tuple[str, ...], str]] = {}
        self._changed: set[str] = set()

    # -- 事件入口 -------------------------------------------------------------

    def on_event(self, e: Event) -> tuple[str, ...]:
        """返回本次事件**改动了观测**的路径（reducer 只重写这几条，保持增量）。"""
        self._changed = set()
        if e.kind == KIND_TOOL_USE:
            self._on_use(e)
        elif e.kind == KIND_TOOL_RESULT:
            self._on_result(e)
        return tuple(sorted(self._changed))

    def _on_use(self, e: Event) -> None:
        is_write, read_only, replay = _classify(e.tool, e.inputs)
        if is_write:
            # 写**锚在回执那一行**（V1 的 `_Write.idx` 是 tool_result 节点号）：变更是
            # 被确认才成立的。锚在调用行会让 `stale_at` 比 V1 早一行——实测正是本轮
            # 对账里唯一残留的不等值项。
            if e.call_id:
                self._pend_write[e.call_id] = (e.paths, _write_summary(e.tool, e.inputs))
            return
        if not read_only:
            return
        precise = e.tool in PRECISE_READ_TOOLS
        if not precise and not _full_file_read(replay):
            return
        if e.call_id:
            self._pend[e.call_id] = (e.tool, e.inputs, e.paths, precise)

    def _on_result(self, e: Event) -> None:
        if e.call_id:
            w = self._pend_write.pop(e.call_id, None)
            if w is not None and not e.is_error:
                paths, summary = w
                for p in paths:
                    self._track(p).writes.append((e.index, summary))
                    self._changed.add(p)
        pend = self._pend.pop(e.call_id, None) if e.call_id else None
        if pend is None or e.is_error:
            return
        _tool, inputs, paths, precise = pend
        for p in paths:
            tr = self._track(p)
            tr.last_obs_idx = e.index
            tr.observed_ever = True
            self._changed.add(p)
            if not precise:
                continue
            tr.hash_src_idx = e.index
            tr.hash_text = e.text
            rng = _read_range(inputs, e.text)
            if rng is not None:
                tr.precise_ranges.append(rng)

    # -- 出账 ---------------------------------------------------------------

    def observe(self, path: str) -> Observation | None:
        tr = self._tracks.get(path)
        return None if tr is None else self._observe(path, tr)

    def snapshot(self) -> dict[str, Observation]:
        return {p: self._observe(p, tr) for p, tr in self._tracks.items()}

    def _observe(self, p: str, tr: _PathTrack) -> Observation:
        if not tr.observed_ever:
            # 只写未读：V1 也进状态表（否则是盲区），但**不判 stale**，摘要取最后一次写。
            return Observation(path=p, last_read_index=-1,
                               diff_summary=tr.writes[-1][1] if tr.writes else "")
        after = [(i, s) for i, s in tr.writes if i > tr.last_obs_idx]
        return Observation(
            path=p,
            observed_hash=_content_hash(tr.hash_text) if tr.hash_src_idx >= 0 else "",
            last_read_index=tr.hash_src_idx if tr.hash_src_idx >= 0 else tr.last_obs_idx,
            read_ranges=_merge_ranges(set(tr.precise_ranges)),
            stale=bool(after),
            stale_at=after[0][0] if after else -1,
            diff_summary="；".join(s for _i, s in after[:3]))

    def _track(self, p: str) -> _PathTrack:
        return self._tracks.setdefault(p, _PathTrack())


# -- V1 判据的薄封装（V1 不可用时退回等价本地实现，方便单测与离线跑） ----------


def _classify(name: str, inp: Mapping[str, Any]) -> tuple[bool, bool, str]:
    try:
        from synaptic.textutil import classify_tool

        return classify_tool(name, dict(inp))
    except Exception:
        n = "".join(ch for ch in str(name).casefold() if ch.isalnum())
        return ("write" in n or "edit" in n, n in ("read", "readfile", "cat"), "")


def _full_file_read(replay_cmd: str) -> bool:
    try:
        from synaptic.textutil import is_full_file_read

        return bool(is_full_file_read(replay_cmd))
    except Exception:
        return str(replay_cmd or "").strip().startswith(("cat", "Get-Content", "type "))


def _read_range(inp: Mapping[str, Any], content: str) -> tuple[int, int] | None:
    try:
        from synaptic.textutil import read_range

        got = read_range(dict(inp), content)
        if got is not None:
            return (int(got[0]), int(got[1]))
    except Exception:
        pass
    return None


def _content_hash(text: str) -> str:
    try:
        from synaptic.textutil import content_hash

        return content_hash(text)
    except Exception:
        import hashlib

        return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:16]


def _write_summary(name: str, inp: Mapping[str, Any]) -> str:
    """变更摘要**必须与 V1 逐字一致**，否则 `diff_summary` 对账对不上。"""
    try:
        from synaptic.filestate import _write_summary as v1

        return v1(str(name or ""), dict(inp))
    except Exception:
        pass
    if name == "Write":
        body = str(inp.get("content") or "")
        return f"Write 全文覆盖（{body.count(chr(10)) + 1} 行 / {len(body)} 字符）"
    return f"{name} 变更"


# -- 对账金标：V1 自己的文件状态表 -------------------------------------------


def v1_file_oracle(msgs: Sequence[Mapping[str, Any]]) -> dict[str, Observation]:
    """跑 V1 的 `build_file_states` 全量版，摊成同一种 `Observation` 供对账。

    只在离线/审计用：它按整份转录重算，成本是 V1 那一档（几十 ms），不是运行时路径。
    """
    from synaptic.filestate import build_file_states
    from synaptic.graph import build_graph

    states = build_file_states(build_graph([dict(m) for m in msgs]),
                               [dict(m) for m in msgs])
    out: dict[str, Observation] = {}
    for p, s in states.items():
        out[p] = Observation(path=p, observed_hash=s.observed_hash,
                            last_read_index=s.last_read_idx,
                            read_ranges=tuple(s.read_ranges), stale=bool(s.stale),
                            stale_at=s.stale_at, diff_summary=s.diff_summary)
    return out


# -- 约束：V1 的确定性抽取器 + 生命周期 UNKNOWN --------------------------------


def constraint_signals(events: Sequence[Event], *, limit: int = 12) -> list[Signal]:
    """从 user 原文抽约束句，用 **V1 的** `extract_constraints`（正则，不猜语义）。

    生命周期是 ``UNKNOWN``：一句话有没有被后来的对话作废，没有 deterministic 判据
    （§十一.4）⇒ reducer 只登记不淘汰，projector 必须把它渲染成"寿命未定"而不是当前结论。
    """
    try:
        from synaptic.seeds import extract_constraints as v1_extract

        def extract(text: str) -> Sequence[str]:
            return v1_extract(text, limit=limit)
    except Exception:
        return []
    out: list[Signal] = []
    for e in events:
        if e.kind != KIND_USER_TEXT:
            continue
        for c in extract(e.text):
            out.append(Signal("constraint", fingerprint(c, width=14),
                              {"literal": c}, DERIVED, "extract_constraints",
                              (e.event_id,)))
    return out


# -- 分支结论：复用 V1 的剪枝卡，但给它 V1 没有的"退场" ------------------------

def error_sig(text: str) -> str:
    """V1 的错误签名原语（`textutil.extract_error_sig`）。

    退场规则要靠它把"卡片记的那次失败"和"V2 记的那条失败事实"对上，
    所以两边必须是**同一个函数**——自造一份就会像 #32 那样键域错位。
    """
    try:
        from synaptic.textutil import extract_error_sig as v1

        return str(v1(text or "") or "")
    except Exception:
        return " ".join(str(text or "").split())[:120]


def path_touches(e: Event) -> tuple[str, ...]:
    """一条事件"碰过"哪些路径 —— **照 V1 建图那四步抄**，不自创口径。

    V1 在 `synaptic/graph.py:412-430` 对每个节点做的事：
      ① tool_use 输入里的路径（`tool_input_paths`）＋命令里的路径（`command_paths`）；
      ② tool_result 输出文本里扫出的路径（前 8k 字符、最多 12 条）；
      ③ 前两条都没扫到，才退回节点正文扫描；
      ④ 过 `is_noise_path`（机器噪音路径根本不进索引）。
    变体归并（同一文件的长短写法折成最短写法）V1 在建图时全局做一次；这里**不做**，
    留给渲染时按当前池子做（`projector._paths_lines`）——池子会随会话长，增量地重算
    归并是 O(n²)，而它只影响"显示成什么"，不影响"碰没碰过"。

    存在的理由：V2 的 `FileObserver` 刻意只认 read/write 工具**输入里**的路径（那才是
    "文件状态"的证据）。但"结果文本里提到过某个文件"也是信息 —— V1 把它和状态混在同一个
    `refs` 池里，所以它的 `[PATHS]` 每 100 tok 能值 15.6 根针（§6.6）。V2 要拿回这块覆盖，
    就得有第二条账，而这条账必须与 V1 同判据，否则两边对不上（#30 那次键域错位的教训）。
    """
    try:
        from synaptic.textutil import (command_paths, extract_paths, is_noise_path,
                                       tool_input_paths)
    except Exception:  # pragma: no cover - 没有 V1 就没有同判据，宁可不记也不自造口径
        return ()

    found: list[str] = []
    if e.kind == KIND_TOOL_USE:
        found = list(tool_input_paths(e.inputs)) + list(command_paths(e.inputs))
    elif e.kind == KIND_TOOL_RESULT:
        found = list(extract_paths(str(e.text or "")[:8000], limit=12))
    if not found:
        found = list(extract_paths(str(e.text or "")[:8000], limit=12))
    out: list[str] = []
    for p in found:
        s = str(p or "")
        if not s or is_noise_path(s):
            continue
        out.append(_norm(s))
    return tuple(dict.fromkeys(out))


def _norm(raw: str) -> str:
    """路径键归一：与 events 同一套（V1 的 `tool_input_paths` 为权威）。"""
    from .events import _norm_path

    return _norm_path(raw)


def _card_get(card: Any, name: str, default: Any = None) -> Any:
    if isinstance(card, Mapping):
        return card.get(name, default)
    return getattr(card, name, default)


def decision_signals(cards: Sequence[Any]) -> list[Signal]:
    """V1 剪枝卡 → 分支结论事实。

    key 用 `(error_sig, files)` 而不是 `card_id`：V1 的渲染层本来就按这个键合组
    （`prune._merge_key` 的注释记录了为什么），换 id 会让同一件事在不同点生成两条事实。
    `nodes` 折成**行区间**存着 ⇒ 取回靠 Event Store 的行号，不靠 V1 的 `branch://` 句柄。
    """
    out: list[Signal] = []
    for c in cards:
        nodes = tuple(int(i) for i in (_card_get(c, "nodes", ()) or ()))
        files = tuple(str(f) for f in (_card_get(c, "files", ()) or ()))
        sig = str(_card_get(c, "error_sig", "") or "")
        key = fingerprint(f"{sig}|{','.join(sorted(files))}", width=16)
        out.append(Signal(
            "decision", key,
            {"conclusion": str(_card_get(c, "conclusion", "") or ""),
             "files": list(files), "error_sig": sig,
             "replay": str(_card_get(c, "replay", "") or ""),
             "rows": [min(nodes), max(nodes)] if nodes else [],
             "n_nodes": len(nodes),
             "card_ids": [str(_card_get(c, "card_id", ""))]},
            DERIVED, "prune_card",
            tuple(f"node:{i}" for i in nodes)))
    return out


def attach_decisions(state: WorkingState, signals: Sequence[Signal]) -> int:
    """把分支结论登记进状态（幂等：同一 key 不重复建事实）。返回新建条数。"""
    made = 0
    for sig in signals:
        if state.latest(sig.kind, sig.key) is not None:
            continue
        state.add(sig.kind, sig.key, dict(sig.value),
                  event_id=sig.provenance[0] if sig.provenance else "prune",
                  event_index=int(sig.value["rows"][0]) if sig.value.get("rows") else 0,
                  evidence=sig.evidence, provenance=sig.provenance,
                  authority=sig.authority)
        made += 1
    retire_decisions(state)
    return made


def retire_decisions(state: WorkingState) -> int:
    """V1 做不到的那一步：错误已被"同参数重试成功"解决 ⇒ 那次被排除的分支作废。

    V1 的剪枝卡永不退场，只是被预算挤出去（信息还在，但没人告诉你它已经不相关了）。
    这里只认一种证据：卡片的 `error_sig` 与某条**已解决**失败的 `error_sig` 完全相等。

    还要反过来查一遍：**同一签名若仍有未解决的失败，就不许退场**。缺这道闸时状态自相
    矛盾——一边说"这个错误已经解决了"，一边 `[UNRESOLVED]` 里挂着同签名的失败。
    实测（`docs/wsc2-v2-parity.md` §5）也证明它对应得上：126 点里 26 次退场有 8 次
    之后同签名错误又出现，其中先于 t 出现的那批就是这道闸能拦的。
    """
    resolved = {str(f.value.get("error_sig") or "")
                for f in state.facts.values()
                if f.kind == "failure" and f.status == RESOLVED
                and f.evidence == "identical_retry_succeeded"}
    resolved.discard("")
    if not resolved:
        return 0
    still_open = {str(f.value.get("error_sig") or "")
                  for f in state.active_facts(("failure",))}
    still_open.discard("")
    resolved -= still_open
    if not resolved:
        return 0
    n = 0
    for f in state.active_facts(("decision",)):
        if str(f.value.get("error_sig") or "") in resolved:
            state.transition(f, SUPERSEDED, event_id=f.fact_id, event_index=f.last_index,
                             evidence="same_error_resolved")
            n += 1
    return n
