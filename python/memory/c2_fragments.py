"""Capture recoverable C2 facts with unique per-message fragment identities."""
import hashlib


def store_c2_fragments(working, left: list[dict]) -> None:
	"""A2：把左区结构化原子全文抓拍进 sqlite（``notes:msg:<i>`` 可 retrieve 还原）。

	优先级保证：最近报错栈永远排第一（总量封顶也轮不到它被裁掉）；其余按
	(kind, 出现序) 抓拍。同文本去重（12× 循环副本不再浪费封顶额度）。失败
	静默——还原是增强项。
	"""
	from memory.runtime import (
		_restore_enabled, _last_traceback_atom, _msg_payload_texts,
	)
	try:
		if not _restore_enabled() or not (working.session_id or "").strip():
			return
		from memory import memindex
		from memory.fidelity_segmenter import split_into_atoms

		keep_kinds = {"stack", "kv", "path", "json", "tree", "table"}
		rows: list[dict] = []
		seen_text: set[str] = set()
		sequences: dict[tuple[int, str], int] = {}

		def _push(i: int, kind: str, text: str) -> None:
			sig = f"{kind}:{hashlib.sha1(text.encode('utf-8', 'replace')).hexdigest()}"
			if sig in seen_text or not text.strip():
				return
			seen_text.add(sig)
			key = (i, kind)
			seq = sequences.get(key, 0)
			sequences[key] = seq + 1
			rows.append({"msg_index": i, "kind": kind, "seq": seq, "text": text})

		# ① 最近报错栈优先
		tb = _last_traceback_atom(left)
		if tb is not None:
			_push(tb[0], "stack", tb[1])
		# ② 全区结构化原子
		for i, msg in enumerate(left):
			for text in _msg_payload_texts(msg):
				try:
					atoms = split_into_atoms(text)
				except AssertionError:
					continue
				for atom in atoms:
					if atom.kind not in keep_kinds:
						continue
					_push(i, atom.kind, atom.text)
				if len(rows) >= 2000:
					break
			if len(rows) >= 2000:
				break
		memindex.store_fragments(working.session_id, rows)
	except Exception:  # noqa: BLE001 — 增强项绝不阻塞压缩热路径
		pass
