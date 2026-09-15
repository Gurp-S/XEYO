"""路径针回归：假点号链过滤、近期路径优先级与 basename 存活口径。"""

from __future__ import annotations

from synaptic.filestate import FileState, working_set
from synaptic.graph import build_graph
from synaptic.metrics import needle_survival
from synaptic.seeds import recent_paths
from synaptic.textutil import extract_paths
from wsc._fixtures import msg_asst_text, msg_asst_use, msg_tool, msg_user, synth_session


def test_extract_paths_rejects_dotted_call_chains():
	text = " ".join(("block.get", "mss.mss", "sct.grab", "img.rgb", "os.path", "torch.nn"))
	assert extract_paths(text) == ()


def test_extract_paths_preserves_real_code_and_docs_names():
	text = "README.md requirements.txt src/auth.ts scripts/build.ps1 docs/guide.zzz"
	paths = extract_paths(text)
	assert "README.md" in paths
	assert "requirements.txt" in paths
	assert "src/auth.ts" in paths
	assert "scripts/build.ps1" in paths
	assert "docs/guide.zzz" in paths, "带目录分隔符的非黑名单扩展名不应被白名单误杀"


def test_path_recent_uses_same_basename_relaxation_as_path():
	hot = "[WORKING SET] auth.ts | src/auth.ts"
	out = needle_survival(hot, {"path": ("src/auth.ts",), "path_recent": ("src/auth.ts",)})
	assert out["path"]["rate"] == 1.0
	assert out["path_recent"]["rate"] == 1.0


def _state(path: str, idx: int) -> FileState:
	return FileState(path=path, observed_hash="h", last_read_idx=idx, read_ranges=())


def test_working_set_puts_recent_paths_before_newer_rest():
	states = {
		"pin.py": _state("pin.py", 1),
		"recent.py": _state("recent.py", 2),
		"newer.py": _state("newer.py", 9),
		"other.py": _state("other.py", 4),
	}
	ws = working_set(
		states,
		limit=3,
		pin_paths=("pin.py",),
		recent_paths=("recent.py",),
	)
	assert [s.path for s in ws] == ["pin.py", "recent.py", "newer.py"]


def test_recent_paths_matches_harvest_region_tail():
	msgs = [msg_user("goal"), msg_asst_text("a")]
	for i in range(4):
		msgs.append(msg_user(f"u{i}"))
		msgs.append(msg_asst_text(f"a{i}"))
	g = build_graph(msgs)
	assert recent_paths(g, region_end=len(msgs)) is not None
	# 没有 refs 的纯文本会话不应凭空制造路径。
	assert recent_paths(g, region_end=len(msgs)) == ()


# ---------------------------------------------------------------------------
# [PATHS]（P0-1）：路径的第四条渲染通道 + 强制配额
# ---------------------------------------------------------------------------


def test_shortest_unique_suffix_disambiguates_homonyms():
	from synaptic.paths import shortest_unique_suffix

	pool = frozenset({"src/a/util.ts", "src/b/util.ts", "src/c/only.ts"})
	assert shortest_unique_suffix("src/c/only.ts", pool) == "only.ts"
	assert shortest_unique_suffix("src/a/util.ts", pool) == "a/util.ts"
	assert shortest_unique_suffix("src/b/util.ts", pool) == "b/util.ts"
	# 无同名时压到基名（针的宽松口径命中基名，模型也不需要绝对路径才知道是哪个文件）
	assert shortest_unique_suffix("src/auth.ts", frozenset({"src/auth.ts"})) == "auth.ts"


def test_paths_segment_emits_recent_paths_within_quota():
	"""配额内的路径必须真的进热层，且条数不超过 path_index_limit。"""
	from synaptic.assemble import H_PATHS
	from synaptic.project import default_params, project

	msgs = synth_session(turns=8)
	# 区域内尾部插入三条不同路径：它们不在 working set 的 12 条里，也不一定进 kept
	for i, p in enumerate(("src/alpha/one.ts", "src/beta/two.ts", "src/gamma/deep/three.ts")):
		uid = f"x{i}"
		msgs.append(msg_asst_use(uid, "Read", {"path": p}))
		msgs.append(msg_tool(uid, "Read", f"// {p}"))
	params = default_params()
	proj = project(msgs, region_end=len(msgs) - 1, params=params)
	hot = proj.text
	assert H_PATHS in hot, "路径段没有发射"
	# 热层是「逐行带段头」的形态（每行前缀 [PATHS]），所以按行筛段内条目。
	section = [ln for ln in hot.splitlines() if ln.startswith(H_PATHS)]
	assert 1 <= len(section) <= params.path_index_limit
	assert any("one.ts" in ln for ln in section), section


def test_paths_quota_is_bounded_by_tokens():
	"""token 上限优先于条数上限：预算缩到 0 时应当一条都不发（而不是超预算硬发）。"""
	from synaptic.paths import render_paths
	from synaptic.project import default_params
	from synaptic.seeds import collect_seeds
	from synaptic.filestate import build_file_states

	msgs = synth_session(turns=6)
	g = build_graph(msgs)
	fs = build_file_states(g, msgs)
	seeds = collect_seeds(g, msgs, fs)
	base = default_params()
	assert render_paths(g, seeds, region_end=len(msgs), kept=(), params=base)
	zero = type(base)(**{**base.__dict__, "path_index_budget_tokens": 0})
	assert render_paths(g, seeds, region_end=len(msgs), kept=(), params=zero) == []

