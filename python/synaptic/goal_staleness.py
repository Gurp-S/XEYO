"""Opt-in goal retirement from explicit, topic-matching user declarations.

No stored message or emitted head is rewritten. Quoted examples, hypothetical
and negated closures are excluded; task replacement is not a closure signal.
"""
from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from synaptic.seeds import _substantive, strip_machine_blocks, extract_constraints
from synaptic.types import KIND_USER

if TYPE_CHECKING:
    from synaptic.freshness import Downgrade
    from synaptic.graph import Graph


ENV = "XEYO_STALE_GOAL_RETIRE"
_GOAL_CLOSE_MARKERS = (
    "我自己修好了", "我自己修复好了", "我自己已经修复好了",
    "已经修好了", "已自行修复", "自己搞定了", "不用管了",
    "这个不用了", "跳过这个", "已解决", "作废",
)
_SENTENCES = re.compile(r"[。！？；!?;\n]+")
_QUOTES = re.compile(r'''```.*?```|`[^`]*`|“[^”]*”|「[^」]*」|"[^"\n]*"|'[^'\n]*' ''', re.S | re.X)
_NON_ASSERTION = re.compile(
    r"如果|假如|假设|例如|示例|举例|比如|是否|有没有|还没|尚未|没有|未能|并非|不是|不算"
    r"|不要|不能|不应|不该|还在|仍在|尚需|仍需|关键词|标记|检测|模式|规则|未|没|\bnot\b"
)
_REOPEN = re.compile(r"继续(?:修复|处理|解决|排查)|重新(?:修复|处理|解决|排查)|仍(?:需|要)|还(?:需|要)")
_REOPEN_NON_ASSERTION = re.compile(r"如果|假如|假设|例如|示例|举例|比如|是否|不需要|无需|不要|不能|不应|不该|关键词|标记|检测|模式|规则")


def enabled() -> bool:
    return os.environ.get(ENV, "").strip().lower() in {"1", "true", "on", "yes"}


def declaration_sentences(text: str) -> tuple[str, ...]:
    text = strip_machine_blocks(text, preserve_layout=True)
    text = _QUOTES.sub(" ", text)
    return tuple(s.strip() for s in _SENTENCES.split(text)
                 if s.strip() and not s.lstrip().startswith((">", "#")))


def closes(text: str, target: str) -> bool:
    from synaptic.freshness import _tokens, _is_cjk_bigram
    topic = _tokens(target)
    for sentence in declaration_sentences(text):
        for marker in _GOAL_CLOSE_MARKERS:
            pos = sentence.find(marker)
            if pos < 0:
                continue
            # Negation/hypothetical language is scoped to the closure clause,
            # not a later paragraph's example or an unrelated earlier request.
            prefix = sentence[:pos + len(marker)]
            clauses = re.split(r"[,，]", prefix)
            clause = clauses[-1]
            if _NON_ASSERTION.search(clause):
                continue
            subject = clause
            if len(clauses) > 1 and any(p in clause for p in ("这个", "这件", "该问题")):
                subject = clauses[-2] + "，" + clause
            if _NON_ASSERTION.search(subject):
                continue
            shared = topic & _tokens(subject)
            need = 2 if any(not _is_cjk_bigram(t) for t in shared) else 3
            if len(shared) >= need:
                return True
    return False


def goal_superseders(graph: Graph, region_end: int,
                     user_nodes: tuple[int, ...]) -> list[Downgrade]:
    from synaptic.freshness import Downgrade
    if not enabled():
        return []
    users = [graph.node(i) for i in sorted(set(user_nodes)) if i < region_end]
    users = [n for n in users if n is not None and n.kind == KIND_USER
             and _substantive(n.text)]
    out = []
    for goal in users:
        target = strip_machine_blocks(goal.text)
        # Whole-node supersession would also remove this message's standing
        # constraints. Such mixed messages remain outside this conservative arm.
        if extract_constraints(target):
            break
        by = next((n for n in users if n.idx > goal.idx and closes(n.text, target)), None)
        if by is None:
            break
        out.append(Downgrade(idx=goal.idx, by=by.idx, cls="goal", key=target[:48],
                             why="后续用户关闭声明且主题重合"))
    return out


def reopened_after(graph: Graph, downgrade: Downgrade, region_end: int) -> tuple[int, ...]:
    """Observed explicit return to a retired topic, for offline mis_downgrade audit."""
    from synaptic.freshness import _tokens, _is_cjk_bigram
    target = graph.node(downgrade.idx)
    if target is None:
        return ()
    topic = _tokens(strip_machine_blocks(target.text))
    out = []
    for node in graph.nodes:
        if node.kind != KIND_USER or not downgrade.by < node.idx < region_end:
            continue
        for sentence in declaration_sentences(node.text):
            if not _REOPEN.search(sentence) or _REOPEN_NON_ASSERTION.search(sentence):
                continue
            shared = topic & _tokens(sentence)
            need = 2 if any(not _is_cjk_bigram(t) for t in shared) else 3
            if len(shared) >= need:
                out.append(node.idx)
                break
    return tuple(out)
