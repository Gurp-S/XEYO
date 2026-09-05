"""下次怎么找回来。P0 = 索引过滤 + 词法扫描 memdir；禁止在本函数里调模型。

多语言策略（无外部分词器）：
- NFKC 归一化（全角/兼容形）
- 拉丁 / 数字：空格或词界 AND
- CJK（中日韩统一表意 + 假名）：字 bigram/trigram，OR 但至少 2 个 term 命中
- 谚文 Hangul：按音节块（已是「词」粒度）OR
跨语种语义（英问中答）不在本层；留给日后 embedding / 双语别名表。

跨会话共享（search_session_notes）：workspace memdir 按 workspace_id 隔离，
同工作区天然共享；但每个会话自己的任务语义笔记（L5b session.md）默认
只回灌本会话。这里把同工作区其他会话的 session.md 纳入同一套词法检索，
命中即带会话归属返回 —— 对话因此能看到别的对话聊过什么。
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass

from memory.governance import MemoryNote, today_iso
from memory.memdir import (
	load_index_text,
	load_notes_for_search,
	note_location,
	touch_last_used,
	workspace_id,
)

_LATIN_TOKEN = re.compile(r"[a-z0-9_]+", re.I)
# CJK 统一表意 + 扩展 A + 平假名/片假名
_CJK_CHAR = re.compile(
	r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
	r"\u3040-\u309f\u30a0-\u30ff]"
)
_HANGUL_SYL = re.compile(r"[\uac00-\ud7a3]+")


def _recency_bonus(note: MemoryNote) -> float:
	"""最近使用 / 确认的笔记略加权（同一天 +2，否则 0）。"""
	stamp = note.last_used_at or note.last_confirmed_at or note.updated_at
	if not stamp:
		return 0.0
	try:
		return 2.0 if str(stamp)[:10] == today_iso() else 0.5
	except Exception:
		return 0.0


# --------------------------------------------------------------------------- #
# F4（v61采纳说明-V2）：查询感知重排（只为「排序」服务，绝不改召回集）。
# 现有词法分把「重复命中单一词」无限加分（depth），导致高频窄语义笔记压过
# 覆盖整条查询的笔记。重排把词频封顶，改为奖励「覆盖不同查询词」（breadth）。
# 纯词法、无模型调用（满足本文件首行「禁止调模型」）。**已固化开启**
# （原 XEYO_MEMORY_QUERY_REWEIGHT 键已删；召回集仍绝不改动）。
# --------------------------------------------------------------------------- #

_QUERY_TERM_CAP = 3


def _note_hay(note: MemoryNote) -> str:
	"""检索打分平面：type/title/content/id 归一化拼接。"""
	return _normalize_query(f"{note.type} {note.title} {note.content} {note.id}")


def score_note(
	note: MemoryNote,
	q: str,
	terms: list[str],
	hay: str | None = None,
	*,
	reweight: bool | None = None,
) -> float:
	"""单条 note 的词法分（与 ``search()`` 同口径；rerank_preference_shadow 叠加偏好分用）。

	双重计数修复：``terms`` 在单 blob 查询下首项就是 ``q`` 本身，旧实现
	``hay.count(q) + sum(hay.count(t) for t in terms)`` 把 q 计了两遍，
	高频查询词权重被放大——terms 求和时剔除与 q 相同的项。
	"""
	if hay is None:
		hay = _note_hay(note)
	if reweight is None:
		reweight = query_reweight_enabled()
	if reweight:
		return (
			query_reweight_score(hay, terms)
			+ float(note.confidence or 0.0)
			+ _recency_bonus(note)
		)
	lexical = float(hay.count(q)) if q else 0.0
	lexical += float(sum(hay.count(t) for t in terms if t != q))
	return lexical + float(note.confidence or 0.0) + _recency_bonus(note)


def query_reweight_enabled(cwd: str | None = None) -> bool:
	"""F4 检索重排：**已固化开启**（原 XEYO_MEMORY_QUERY_REWEIGHT 键已删）。

	q 双重计数缺陷已修（score_note 统一口径）且广度主导排序过离线 A/B；回退只能
	改本函数源码。cwd 参数保留以兼容既有调用点。
	"""
	_ = cwd
	return True


def query_reweight_score(hay: str, terms: list[str]) -> float:
	"""F4 重排分：每个区分查询词的命中数封顶到 _QUERY_TERM_CAP，广度主导深度。
	返回封顶后的覆盖分；作者拿它替换 raw lexical（同 置信度 + 近因 组合）。"""
	distinct = {t for t in terms if len(t) >= 2}
	if not distinct:
		return 0.0
	return float(sum(min(hay.count(t), _QUERY_TERM_CAP) for t in distinct))


def _normalize_query(q: str) -> str:
	return unicodedata.normalize("NFKC", (q or "").strip()).lower()


def _cjk_ngrams(text: str) -> list[str]:
	chars = _CJK_CHAR.findall(text)
	if not chars:
		return []
	out: list[str] = []
	for n in (2, 3):
		if len(chars) < n:
			continue
		for i in range(len(chars) - n + 1):
			gram = "".join(chars[i : i + n])
			if gram not in out:
				out.append(gram)
	return out


def _query_terms(q: str) -> tuple[list[str], bool, int]:
	"""拆查询词 → (terms, require_all, min_or_hits)。

	min_or_hits：OR 模式下至少命中几个 term（降低单 bigram 误召）。
	"""
	spaced = [w for w in q.split() if w]
	if len(spaced) > 1:
		# 多词：若几乎全是拉丁 → AND；含 CJK 块则拆开后 OR+门槛
		cjk_chunks = []
		latin_parts = []
		for w in spaced:
			cjk_chunks.extend(_cjk_ngrams(w))
			latin_parts.extend(_LATIN_TOKEN.findall(w))
			latin_parts.extend(_HANGUL_SYL.findall(w))
		if cjk_chunks or any(_HANGUL_SYL.search(w) for w in spaced):
			terms = list(dict.fromkeys(spaced + cjk_chunks + latin_parts))
			# 小库词法召回：OR 命中 1 个有信息 ngram 即可；排序靠 lexical 分
			return terms, False, 1
		return spaced, True, 1

	blob = spaced[0] if spaced else q
	latin = _LATIN_TOKEN.findall(blob)
	hangul = _HANGUL_SYL.findall(blob)
	cjk = _cjk_ngrams(blob)
	compact = re.sub(r"\s+", "", blob)
	if latin and "".join(latin) == compact and not cjk and not hangul:
		return latin, True, 1

	terms: list[str] = [blob]
	for tok in cjk + hangul + latin:
		if tok not in terms:
			terms.append(tok)
	return terms, False, 1


def _term_hit(term: str, hay: str, index: str) -> bool:
	return len(term) >= 2 and (term in hay or term in index)


def _matches(
	hay: str,
	index: str,
	q: str,
	terms: list[str],
	require_all: bool,
	min_or_hits: int,
) -> bool:
	if q and (q in hay or q in index):
		return True
	if not terms:
		return False
	if require_all:
		return all(t in hay or t in index for t in terms)
	hits = sum(1 for t in terms if _term_hit(t, hay, index))
	return hits >= max(1, min_or_hits)


def note_citation_text(note: MemoryNote, wsid: str) -> str:
	"""检索命中的引用块（``<citation_entries>``+``<rollout_ids>``）或空串。

	条目：notes/topics/<slug>.md:行区间|note=[title]；rollout_ids 取 source.session_id。
	供 Memory(action=search) 展示时把命中锚定到 memdir note 文件与来源会话。
	"""
	from memory.citation import (
		block_for_entries,
		note_file_citation,
		render_block,
		rollout_id_from_source,
	)

	rel, ls, le = note_location(note, wsid)
	entry = note_file_citation(rel, line_start=ls, line_end=le, note=note.title or note.type)
	return render_block(
		block_for_entries([entry], rollout_ids=[rollout_id_from_source(note.source)])
	)


def search(
	query: str,
	*,
	scope: str = "",
	note_type: str = "",
	top_k: int = 5,
	cwd: str | None = None,
	wsid: str | None = None,
	touch: bool = True,
) -> list[MemoryNote]:
	"""按查询和范围返回 Note；词法检索 + 置信度/近因排序；命中可更新 last_used_at。"""
	ident = wsid or workspace_id(cwd or ".")
	q = _normalize_query(query)
	if not q:
		return []
	terms, require_all, min_or_hits = _query_terms(q)
	want_type = (note_type or "").strip().lower()
	notes = [
		n
		for n in load_notes_for_search(ident, scope=scope or "")
		if n.status == "active"
		and (not want_type or (n.type or "").strip().lower() == want_type)
	]
	index_ws = _normalize_query(load_index_text(ident))
	index_user = ""
	try:
		from memory.memdir import USER_MEMDIR_ID

		if ident != USER_MEMDIR_ID:
			index_user = _normalize_query(load_index_text(USER_MEMDIR_ID))
	except Exception:
		index_user = ""
	index = index_ws + "\n" + index_user
	reweight = query_reweight_enabled(cwd)
	scored: list[tuple[float, MemoryNote]] = []
	for note in notes:
		hay = _note_hay(note)
		if not _matches(hay, index, q, terms, require_all, min_or_hits):
			continue
		scored.append((score_note(note, q, terms, hay=hay, reweight=reweight), note))
	scored.sort(key=lambda x: x[0], reverse=True)
	hits = [n for _s, n in scored[: max(1, int(top_k))]]
	if touch:
		out: list[MemoryNote] = []
		for note in hits:
			try:
				out.append(touch_last_used(note, wsid=ident))
			except OSError:
				out.append(note)
		return out
	return hits


# --------------------------------------------------------------------------- #
# 跨会话共享记忆：同工作区其他会话的 session.md（L5b 任务语义笔记）检索。
# --------------------------------------------------------------------------- #

_SCOPED_TOKEN = "__agent__"


@dataclass(frozen=True)
class SessionNoteHit:
	"""一条跨会话命中：来自哪个对话、聊到什么。"""

	session_id: str
	title: str
	excerpt: str
	score: float
	citation: str = ""  # 引用块：notes/session/<sid>.md + rollout_ids=[sid]


def _session_tree_root(session_id: str) -> str:
	sid = (session_id or "").strip()
	if _SCOPED_TOKEN in sid:
		return sid.split(_SCOPED_TOKEN, 1)[0].strip("_")
	return sid


def _peer_candidates(
	cwd: str, self_session_id: str
) -> list[tuple[str, str]]:
	"""同工作区其他会话的 (session_id, title)；self / 子 agent 侧链排除。

	来源两路合并（后者 title 优先）：
	- session/ws_index 落盘归属（跨重启仍可查旧对话）
	- 进程内 presence 表（标题最准）
	"""
	self_root = _session_tree_root(self_session_id)
	peers: dict[str, str] = {}
	try:
		from session.ws_index import sessions_for_workspace

		for sid in sessions_for_workspace(cwd):
			if not sid or _session_tree_root(sid) == self_root:
				continue
			peers.setdefault(sid, "")
	except Exception:  # noqa: BLE001
		pass
	try:
		from engine.session_presence import default_session_presence

		for ent in default_session_presence().peers(cwd, self_session_id):
			sid = (ent.session_id or "").strip()
			if not sid or _session_tree_root(sid) == self_root:
				continue
			if ent.title and ent.title.strip() and ent.title.strip() != sid:
				peers[sid] = ent.title.strip()
			else:
				peers.setdefault(sid, "")
	except Exception:  # noqa: BLE001
		pass
	return list(peers.items())


def _short_sid(session_id: str) -> str:
	sid = (session_id or "").strip()
	if len(sid) <= 10:
		return sid
	return sid[-8:]


def _session_citation(session_id: str, label: str) -> str:
	"""跨会话命中的引用块：notes/session/<sid>.md + rollout_ids=[sid]。"""
	from memory.citation import block_for_entries, note_file_citation, render_block

	sid = (session_id or "").strip()
	if not sid:
		return ""
	entry = note_file_citation(f"notes/session/{sid}.md", note=label)
	return render_block(block_for_entries([entry], rollout_ids=[sid]))


def _goal_topic(text: str, limit: int = 80) -> str:
	"""从 session.md 取 Goal / Current state 首行作话题摘要。"""
	for header in ("## Goal", "## Current state"):
		idx = text.find(header)
		if idx < 0:
			continue
		for line in text[idx + len(header) :].splitlines():
			line = line.strip()
			if not line:
				continue
			if line.startswith("#"):
				break
			if line in ("(unspecified)", "(none)", "(continue)", "(none yet)"):
				break
			return line[:limit]
	return ""


def _note_excerpt(text: str, terms: list[str], q: str, width: int = 220) -> str:
	"""取第一条命中 term 的行；都不命中就取 Goal 话题行。"""
	norm_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
	for line in norm_lines:
		low = line.lower()
		if q in low or any(t in low for t in terms if len(t) >= 2):
			return line[:width]
	topic = _goal_topic(text, limit=width)
	return topic or (norm_lines[0][:width] if norm_lines else "")


def search_session_notes(
	query: str,
	*,
	cwd: str | None = None,
	self_session_id: str = "",
	top_k: int = 5,
) -> list[SessionNoteHit]:
	"""跨会话记忆检索：同工作区其他对话的 session.md 词法扫描。

	与 :func:`search` 共用同一套分词 / 匹配 / 打分；不做 I/O 之外的任何
	模型调用。命中按词频排序，摘录一句并带会话标题返回。
	"""
	root = os.path.realpath(os.path.abspath(os.path.expanduser(cwd or ".")))
	q = _normalize_query(query)
	if not q:
		return []
	terms, require_all, min_or_hits = _query_terms(q)
	try:
		from memory.session_md import load as _load_session_md

		loader = _load_session_md
	except Exception:  # noqa: BLE001
		return []
	hits: list[SessionNoteHit] = []
	reweight = query_reweight_enabled(cwd)
	for sid, title in _peer_candidates(root, self_session_id):
		try:
			text = loader(sid) or ""
		except Exception:  # noqa: BLE001
			continue
		if not text.strip():
			continue
		hay = _normalize_query(f"{title} {text}")
		if not _matches(hay, "", q, terms, require_all, min_or_hits):
			continue
		lexical = float(hay.count(q)) if q else 0.0
		lexical += float(sum(hay.count(t) for t in terms if t != q))
		score = query_reweight_score(hay, terms) if reweight else lexical
		label = title or _goal_topic(text, limit=40) or _short_sid(sid)
		citation = _session_citation(sid, label)
		hits.append(
			SessionNoteHit(
				session_id=sid,
				title=label,
				excerpt=_note_excerpt(text, terms, q),
				score=score,
				citation=citation,
			)
		)
	hits.sort(key=lambda h: h.score, reverse=True)
	return hits[: max(1, int(top_k))]


# --------------------------------------------------------------------------- #
# P2-2 任务级 rollout 归档检索：memdir/rollout_summaries/*.md（喂 L4）。
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class RolloutHit:
	"""一份历史任务归档命中。"""

	session_id: str
	file_name: str
	title: str
	excerpt: str
	score: float
	citation: str = ""  # 引用块：rollout_summaries/<file>.md:行号 + rollout_ids=[sid]


def _load_rollout(path) -> tuple[str, dict] | None:
	"""读 rollout 归档：返回 (全文, 元数据)；无规整 frontmatter 时元数据为空。"""
	try:
		raw = path.read_text(encoding="utf-8")
	except OSError:
		return None
	if not raw.startswith("---"):
		return raw, {}
	close = raw.find("\n---", 3)
	if close < 0:
		return raw, {}
	meta: dict = {}
	for line in raw[3:close].splitlines():
		if ":" in line:
			k, v = line.split(":", 1)
			meta[k.strip()] = v.strip()
	return raw, meta


def _rollout_citation(file_name: str, line_no: int | None, session_id: str, title: str) -> str:
	from memory.citation import block_for_entries, note_file_citation, render_block

	entry = note_file_citation(
		f"rollout_summaries/{file_name}", line_start=line_no, line_end=line_no, note=title
	)
	return render_block(block_for_entries([entry], rollout_ids=[session_id]))


def _excerpt_and_line(raw: str, q: str, terms: list[str], width: int = 220) -> tuple[str, int | None]:
	"""取第一条命中行的文本与 1-based 绝对行号；都不命中取首个非空行。"""
	for idx, line in enumerate(raw.splitlines()):
		low = line.strip().lower()
		if low and (q in low or any(t in low for t in terms if len(t) >= 2)):
			return line.strip()[:width], idx + 1
	first = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
	return first[:width], None


def search_rollout_summaries(
	query: str, *, cwd: str | None = None, wsid: str | None = None, top_k: int = 5
) -> list[RolloutHit]:
	"""词法检索任务级 rollout 归档（同一套分词/匹配/打分；只读目录，无模型调用）。

	归档由 ``session_md.archive_session_rollout`` 在会话/任务结束时写一次；
	命中带 ``rollout_summaries/<file>.md:行号|note=[title]`` + rollout_ids 引用锚点。
	"""
	ident = wsid or workspace_id(cwd or ".")
	q = _normalize_query(query)
	if not q:
		return []
	terms, require_all, min_or_hits = _query_terms(q)
	try:
		from memory.session_md import rollout_dir

		directory = rollout_dir(ident)
	except Exception:  # noqa: BLE001
		return []
	if not directory.is_dir():
		return []
	hits: list[RolloutHit] = []
	reweight = query_reweight_enabled(cwd)
	for path in sorted(directory.glob("*.md")):
		loaded = _load_rollout(path)
		if loaded is None:
			continue
		raw, meta = loaded
		sid = str(meta.get("session_id") or path.stem)
		title = _goal_topic(raw, limit=60) or path.stem[:60]
		hay = _normalize_query(f"{sid} {title} {raw}")
		if not _matches(hay, "", q, terms, require_all, min_or_hits):
			continue
		lexical = float(hay.count(q)) if q else 0.0
		lexical += float(sum(hay.count(t) for t in terms if t != q))
		score = query_reweight_score(hay, terms) if reweight else lexical
		excerpt, line_no = _excerpt_and_line(raw, q, terms)
		hits.append(
			RolloutHit(
				session_id=sid,
				file_name=path.name,
				title=title,
				excerpt=excerpt,
				score=score,
				citation=_rollout_citation(path.name, line_no, sid, title),
			)
		)
	hits.sort(key=lambda h: h.score, reverse=True)
	return hits[: max(1, int(top_k))]
