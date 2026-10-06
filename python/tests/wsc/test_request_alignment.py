"""本轮请求对齐（旁路 ``XEYO_WSC_REQUEST_ALIGN``）——只降权不删。

现场（16 条缺陷 #12）："问的是后端压缩，[PATHS] 塞的是前端在途文件"——工作集是
上一轮遗留、没按本轮请求重排。本对齐把**用户最近一条实质消息**里点名的路径提到
最前一级；候选池、配额、冷层可达性全部不变（A/B 用旁路，默认关）。
"""

from __future__ import annotations

from synaptic.filestate import build_file_states
from synaptic.graph import build_graph
from synaptic.paths import render_paths
from synaptic.seeds import collect_seeds
from synaptic.types import WscParams


def use(uid, tool, inp):
	return {'role': 'assistant', 'content': [
		{'type': 'tool_use', 'id': uid, 'name': tool, 'input': inp}]}


def result(uid, name, text):
	return {'role': 'user', 'content': [
		{'type': 'tool_result', 'tool_use_id': uid, 'content': text, 'is_error': False}],
		'name': name}


def _session():
	"""compact.py 是本轮请求点名的（且只在 kept 池里）；recent 全是更晚触碰的遗留文件。

	发射序与配额序是两条线：配额按"最近触碰优先"选人、发射按"首次出现升序"
	（KV 友好，见 paths.py 模块文档）——所以对齐的效果是**入选**（候选超配额时
	挤掉别人），不是"换到第一行"。
	"""
	msgs = [{'role': 'user', 'content': '先看看代码。'}]
	msgs.append(use('c1', 'Read', {'path': 'python/synaptic/compact.py', 'offset': 1, 'limit': 10}))
	msgs.append(result('c1', 'Read', 'x\ny'))
	# 本轮请求（最后一条实质用户消息）；其后不再有 user 文本消息
	msgs.append({'role': 'user', 'content': '重点看 python/synaptic/compact.py，其它先别动'})
	for i in range(5):
		msgs.append(use(f'r{i}', 'Read', {'path': f'src/old{i}.py', 'offset': 1, 'limit': 10}))
		msgs.append(result(f'r{i}', 'Read', 'a\nb\nc'))
	return msgs


def _paths(msgs):
	graph = build_graph(msgs)
	states = build_file_states(graph, msgs)
	seeds = collect_seeds(graph, msgs, states, region_end=len(msgs))
	# kept 直给：compact 的 use 节点在 kept 里（不进 recent 也能进候选池）
	lines = render_paths(
		graph, seeds, region_end=len(msgs), kept=(1,),
		params=WscParams(path_index_limit=2),
	)
	return [key for key, _ in lines]


def test_alignment_promotes_named_path_into_quota(monkeypatch):
	msgs = _session()
	monkeypatch.delenv("XEYO_WSC_REQUEST_ALIGN", raising=False)
	base = _paths(msgs)
	monkeypatch.setenv("XEYO_WSC_REQUEST_ALIGN", "1")
	aligned = _paths(msgs)
	compact = 'path:python/synaptic/compact.py'
	assert compact not in base, f'off 臂点名项应落选（recent 更近）: {base}'
	assert compact in aligned, f'on 臂点名项应入选: {aligned}'
	assert set(aligned) - set(base) == {compact}, '对齐不许把池外路径拉进配额'


def test_alignment_off_is_byte_identical(monkeypatch):
	"""默认关：两次渲染逐字节一致（不改既有行为）。"""
	monkeypatch.delenv("XEYO_WSC_REQUEST_ALIGN", raising=False)
	msgs = _session()
	assert _paths(msgs) == _paths(msgs)


def test_alignment_off_is_byte_identical(monkeypatch):
	"""默认关：两次渲染逐字节一致（不改既有行为）。"""
	monkeypatch.delenv("XEYO_WSC_REQUEST_ALIGN", raising=False)
	msgs = _session()
	assert _paths(msgs) == _paths(msgs)
