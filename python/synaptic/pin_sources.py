"""Public origins for omitted PIN evidence, independent of body size."""
from dataclasses import replace
from synaptic.coldstore import node_group_handle


def _label_of(signature: str, members) -> str:
	"""签名 + 成员数构成的展示标签（与 ``seeds`` 侧同构）。"""
	return signature if len(members) == 1 else f'{signature}（×{len(members)}）'


def _signature_for_pin(pin, groups: dict, declared) -> str | None:
	"""按**内容身份**定位签名组；歧义即拒（不假装恢复成功）。

	历史缺陷（#1 指针不对齐 / #9 引用身份不稳，同源）：
	原实现用 ``errors[ordinal]`` 的位置身份取组，而 ordinal 与 groups 的插入序
	由两条独立推导产生。错位时唯一的闸门 ``pin.text == label`` 只比文本——
	于是身份错了照样宣称有 source（误导），或静默丢来源（假阴）。

	现在的次序：
	1. 展示文本反查（唯一命中）——与模型可见标签同源，最可信；
	2. 声明签名（``seeds.unresolved_sigs[index]``）且其标签与展示文本一致；
	3. 其余一律 None ⇒ 不绑定来源（歧义 / 失配时宁可空，也不假装绑上）。
	"""
	hits = [sig for sig, members in groups.items() if _label_of(sig, members) == pin.text]
	if len(hits) == 1:
		return hits[0]
	if declared is not None and declared in groups:
		if _label_of(declared, groups[declared]) == pin.text:
			return declared
	return None


def bind_short_pin_sources(pins, seeds, graph, *, region_end, inline_max_tokens):
	groups = {}
	for idx in seeds.pin_nodes:
		node = graph.node(idx)
		if node and node.is_error and node.error_sig:
			groups.setdefault(node.error_sig, []).append(idx)
	declared_sigs = tuple(getattr(seeds, 'unresolved_sigs', ()) or ())
	declared_groups = tuple(getattr(seeds, 'unresolved_source_groups', ()) or ())
	result = []
	for pin in pins:
		sources = ()
		if pin.key.startswith('unresolved:'):
			index = int(pin.key.partition(':')[2])
			if declared_groups:
				if index >= len(declared_groups):
					raise ValueError("unresolved_source_group_missing")
				sources = tuple(i for i in declared_groups[index] if i < region_end)
				result.append(replace(pin, nodes=sources))
				continue
			declared = declared_sigs[index] if index < len(declared_sigs) else None
			signature = _signature_for_pin(pin, groups, declared)
			if signature is not None:
				sources = tuple(
					idx for idx in groups[signature]
					if idx < region_end and graph.node(idx).text not in pin.text
				)
		elif pin.key.startswith('denial:') and getattr(seeds, 'denial_source_groups', ()):
			index = int(pin.key.partition(':')[2])
			sources = tuple(i for i in seeds.denial_source_groups[index] if i < region_end)
		elif pin.key == 'todo:0' and 0 <= seeds.todo_source < region_end:
			source = graph.node(seeds.todo_source)
			if source and source.text not in pin.text:
				sources = (source.idx,)
		result.append(replace(pin, nodes=sources) if sources else pin)
	return tuple(result)


def complete_pin_sources(pins, previous, handles, cold):
	"""Publish earlier missing members while preserving the latest entrance."""
	if previous and previous.full_text:
		covered = handles.recoverable_nodes(previous.full_text)
		pins = tuple(replace(pin, nodes=tuple(idx for idx in pin.nodes[:-1] if idx not in covered) + pin.nodes[-1:])
			if pin.key.startswith(('unresolved:', 'denial:')) and len(pin.nodes) > 1 else pin for pin in pins)
	for pin in pins:
		if pin.key.startswith(('unresolved:', 'denial:')) and len(pin.nodes) > 2:
			earlier = pin.nodes[:-1]
			handle = node_group_handle(earlier)
			cold.bind(handle, earlier)
			handles.handle_nodes[handle] = earlier
	return pins
