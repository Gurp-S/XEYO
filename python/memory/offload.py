"""memory/offload — L3 外部化：超长工具结果卸载到文件 + 固定预览引用。

Link②① 统一 C0/L3 截断：>OFFLOAD_THRESHOLD 的工具结果**直接 offload**（写文件 + 固定预览引用），
**不再走 C0 截断**（8192）——避免"先截断又 offload"的双重处理。

字节稳定红线：引用文本（路径/行数/固定预览）与文件内容都**确定性**，同消息同 uid 每次生成相同引用 → KV 前缀稳定。

**取回走 `Read`**（2026-09-16 用户裁定）：`expand` / `offload` / `Read` 是同一个能力，只保留
一个接口 ⇒ 专用工具 `offload_read` 已**删除**，WSC 冷层取回视图也统一成
「纯文本 + `Read(file_path=…, offset=…, limit=…)`」（与 `tools/spill.py` 的
「落盘 + 告诉模型 Read 这个路径」同策）。

可通过 env 开关：XEYO_TOOL_OFFLOAD=1 开启（默认关，旁路）；XEYO_TOOL_OFFLOAD_CHARS 阈值（默认 128）；
XEYO_TOOL_OFFLOAD_PREVIEW 预览长度（默认 128）。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

OFFLOAD_THRESHOLD = int(os.environ.get("XEYO_TOOL_OFFLOAD_CHARS", "128"))
_PREVIEW = int(os.environ.get("XEYO_TOOL_OFFLOAD_PREVIEW", "128"))
_ENV = "XEYO_TOOL_OFFLOAD"

#: 引用里给出的**一页**行数（模型可自行翻页）。取保守值：一次 `Read` 的上限是
#: `MAX_LINES_TO_READ = 2000`、token 上限 25k ⇒ 给「一页」而不是「读全文」，
#: 模型才不会一次撞上限、白烧一轮。
RETRIEVE_PAGE_LINES = int(os.environ.get("XEYO_OFFLOAD_PAGE_LINES", "400"))


def offload_enabled() -> bool:
	"""L3 offload 是否开启（旁路默认关，字节稳定不因未读工具破坏）。"""
	return os.environ.get(_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def _safe(s: str) -> str:
	return re.sub(r"[^A-Za-z0-9_.-]", "_", s or "x")[:40]


def _offload_root(cwd: str | Path | None = None) -> Path:
	"""offload 落盘根。

	`cwd` 给定时按其相对位置算（**读取侧必须传自己的工作区**，不能用进程 cwd：
	两者在生产里相等——server 以工作区为 cwd 启动——但任何别处都不保证相等，
	`tests/wsc/test_cold_read_view.py` 就是靠这条才测得出问题）。
	"""
	base = os.environ.get("XEYO_OFFLOAD_DIR", "").strip()
	if base:
		return Path(base)
	return Path(str(cwd or os.getcwd())) / ".xeyo_offload"


def maybe_offload(
	raw: str,
	*,
	msg_idx: int,
	uid: str,
	cwd: str | Path | None = None,
) -> tuple[str, str | None]:
	"""超长工具结果：写文件 + 返回固定预览引用。返回 (投影文本, offload文件路径或None)。"""
	if len(raw) <= OFFLOAD_THRESHOLD:
		return raw, None
	p = _offload_root(cwd) / f"{msg_idx}_{_safe(uid)}.tool.txt"
	p.parent.mkdir(parents=True, exist_ok=True)
	p.write_text(raw, encoding="utf-8")
	n = raw.count("\n") + (1 if raw else 0)
	head = raw[:_PREVIEW].replace("\n", " ")
	tail = raw[-_PREVIEW:].replace("\n", " ")
	# 引用正文只承载**信息**：路径 / 行数 / 一段可直接照抄的调用。不写「你应该…」式编排
	# （引擎铁律：注意力里只出现信息，不出现导演）。
	page = min(n, RETRIEVE_PAGE_LINES)
	return (
		f"[tool offloaded: {p} ({n} lines) 头: {head} 尾: {tail} | "
		f"全文: Read(file_path='{p}', offset=1, limit={page})]",
		str(p),
	)


def ref_path_for(path: str | Path, cwd: str | Path | None = None) -> str:
	"""外部化文件的**引用路径**：能给工作区相对路径就给（`Read` 的 cwd = 读取方工作区）。

## 为什么值得单收一层（有实测代价）

引用在每个句柄上重复一次（全语料实测 median **28 个句柄/轮**），而绝对路径很长 ⇒
全语料同口径 A/B（只换句柄形态）：

| 引用形态 | 热层 token median | WSC 总成本 | 压缩率 median（活跃档） |
|---|---:|---:|---:|
| `expand(node://N)` | 2406 | ¥8.134 | 0.8718 |
| `Read(file_path='<绝对路径>', …)` | 3407（**+41.6%**） | ¥8.724（**+7.25%**） | 0.8606（−1.28pp） |
| `Read(file_path='<相对路径>', …)` | **2998**（比绝对 −12.0%，比 expand +24.6%） | **¥8.6041**（比绝对 −2.03%，比 expand +4.97%） | 0.8636 |

同批复测（`_wsc_out/_hb_*`，340 会话 / 247 会话参与 / 771 回合，`read` 相对 vs 绝对）：
热层 token median 3407 → **2998**、总成本 ¥8.7824 → **¥8.6041**、活跃档成本比
0.5918 → **0.5800**、针不变。⇒ 相对引用**必须**用（它同时是更短的引用与更低的成本）。

⚠️ `expand` 档在生产里**没有解析器**（专用工具已删，取回面统一到 `Read`）⇒ 只有
`Read` 两档是「真换上 WSC」的成本；跨形态的 token / 成本**一律不可相减**。

⇒ 路径长度本身就是**热层成本**，不是格式细节。

## 两条硬约束

1. **只在能判定「相对」时才给相对**：目标不在 `cwd` 之下（或 `cwd` 未知）一律回落绝对路径。
   渲染一个解析不了的相对路径 = 坏引用（比没有引用严重：模型会照着它去调、拿回错误）。
2. **分隔符一律 `/`**（`as_posix`）：反斜杠在 JSON 字符串里是转义字符，模型照抄
   `'.xeyo_offload\\wsc'` 形态会写出非法转义 ⇒ 相对路径必须给正斜杠（`Read` 在
   Windows 上同样接受）。
	"""
	try:
		if not cwd:
			raise ValueError("no cwd")
		target = Path(str(path)).expanduser().resolve()
		base = Path(str(cwd)).expanduser().resolve()
		return target.relative_to(base).as_posix()
	except Exception:  # noqa: BLE001 — 判不出相对就回落绝对（方向安全）
		return str(path)


def is_externalized_path(path: str | Path, cwd: str | Path | None = None) -> bool:
	"""该路径是否属于**外部化内容**（offload 落地文件 / 冷层取回视图）。

	用途只有一个：`Read` 读它时**不记 read-state**。理由见 `tools/file_read_tool` 的落点注释——
	外部化内容不是模型在编辑的对象，记进去只会占 `ReadFileState` 的 LRU 槽位
	（挤掉正在编辑的真文件快照，而那份快照是写前新鲜度校验的依据），
	且同一区间重复读会被 `FILE_UNCHANGED_STUB` 顶掉正文（取回语义要求每次给正文）。

	`cwd` 必须是**读取方自己的**工作区（`Read` 传 `self._cwd`）：判定按 offload 根前缀，
	根默认是 ``<cwd>/.xeyo_offload`` ⇒ 用进程 cwd 会在「工作区 ≠ 进程 cwd」时误判
	（实测：测试里 tmp_path 是工作区而进程 cwd 不是，判定返回 False，read-state 照样被写）。
	⇒ WSC 冷层的取回视图也必须落在该根下（阶段 C 接线要求，docs §15.16.6）。
	"""
	try:
		target = Path(str(path)).expanduser().resolve()
		root = _offload_root(cwd).resolve()
	except Exception:  # noqa: BLE001 — 判定失败按「非外部化」处理（退回旧行为，方向安全）
		return False
	try:
		target.relative_to(root)
	except ValueError:
		return False
	return True
