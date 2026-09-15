"""路径针回归：假点号链过滤、近期路径优先级与 basename 存活口径。"""

from __future__ import annotations

from synaptic.filestate import FileState, working_set
from synaptic.graph import build_graph
from synaptic.metrics import needle_survival
from synaptic.seeds import recent_paths
from synaptic.textutil import extract_paths
from wsc._fixtures import msg_asst_text, msg_user, synth_session


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
