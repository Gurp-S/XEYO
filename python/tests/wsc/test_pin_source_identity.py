"""PIN 来源绑定的身份回归：位置身份跨构建不稳时，不得绑错、不得假装绑上。

背景（会话 sess_mux0q86a_ea2kv9 实测）：摘要曾把
``ParameterBindingException…NamedParameterNotFound（×2）`` 挂在 ``source=#468`` 上，
而 #468 实际是另一个节点（``bash-1 [bash] killed``，``is_error=False``，66 字符），
真正的证据节点是 #3（27751 字符，正文含该报错）。

根因：原实现用 ``errors[ordinal]``（**位置**身份）取组，而 ordinal 与 groups 的插入序
由两条独立推导产生；错位时唯一的闸门 ``pin.text == label`` 只比文本——
身份错了照样宣称有 source（误导），顺序错了就静默丢来源（假阴）。

这三条测试钉住的契约：
1. 来源跟随**签名**，不跟随 pin_nodes 的遍历位置；
2. 展示文本无法唯一定位时 ⇒ **不绑定**（不假装恢复成功）；
3. 声明缺失（``unresolved_sigs`` 为空）时，仍可按展示文本唯一反查绑定。
"""

from synaptic.pin_sources import bind_short_pin_sources
from synaptic.types import Pin


class _Node:
	def __init__(self, idx, text, *, is_error=False, error_sig=None):
		self.idx = idx
		self.text = text
		self.is_error = is_error
		self.error_sig = error_sig


class _Graph:
	def __init__(self, nodes):
		self._nodes = {n.idx: n for n in nodes}

	def node(self, idx):
		return self._nodes.get(idx)


class _Seeds:
	def __init__(self, pin_nodes, unresolved_sigs, todo_source=-1):
		self.pin_nodes = tuple(pin_nodes)
		self.unresolved_sigs = tuple(unresolved_sigs)
		self.todo_source = todo_source


def _bind(pins, seeds, nodes):
	return bind_short_pin_sources(
		pins, seeds, _Graph(nodes), region_end=10_000, inline_max_tokens=48
	)


def test_source_follows_signature_not_group_position():
	"""pin_nodes 的遍历序与 pin 声明序相反时，来源仍须落在自己的签名组上。"""
	nodes = [
		_Node(10, 'wrong group body', is_error=True, error_sig='sig B'),
		_Node(11, 'wrong group body too', is_error=True, error_sig='sig B'),
		_Node(20, 'right group body', is_error=True, error_sig='sig A'),
	]
	seeds = _Seeds(pin_nodes=(10, 11, 20), unresolved_sigs=('sig A',))
	pins = (Pin('unresolved:0', '未解决', 'sig A'),)

	out = _bind(pins, seeds, nodes)

	assert out[0].nodes == (20,), f'绑到了同一位置的组：{out[0].nodes}'


def test_ambiguous_label_refuses_to_bind():
	"""展示文本与所有签名组都对不上时：不绑定（不假装恢复成功）。"""
	nodes = [
		_Node(10, 'body', is_error=True, error_sig='sig A'),
		_Node(20, 'body2', is_error=True, error_sig='sig A'),
	]
	seeds = _Seeds(pin_nodes=(10, 20), unresolved_sigs=('sig A',))
	pins = (Pin('unresolved:0', '未解决', 'sig X（×2）'),)

	out = _bind(pins, seeds, nodes)

	assert out[0].nodes == (), f'失配时不该宣称有来源：{out[0].nodes}'


def test_label_lookup_binds_when_declared_signature_missing():
	"""声明缺失（unresolved_sigs 为空）时，仍可按展示文本唯一反查绑定。"""
	nodes = [_Node(10, 'body', is_error=True, error_sig='sig A')]
	seeds = _Seeds(pin_nodes=(10,), unresolved_sigs=())
	pins = (Pin('unresolved:0', '未解决', 'sig A'),)

	out = _bind(pins, seeds, nodes)

	assert out[0].nodes == (10,)


def test_non_error_node_is_never_a_source():
	"""跨构建的陈旧下标若落到非错误节点上，不得被当成来源。"""
	nodes = [
		_Node(10, 'bash-1 [bash] killed', is_error=False),  # 形态同实测 #468
		_Node(20, 'real failure body', is_error=True, error_sig='sig A'),
	]
	seeds = _Seeds(pin_nodes=(10, 20), unresolved_sigs=('sig A',))
	pins = (Pin('unresolved:0', '未解决', 'sig A'),)

	out = _bind(pins, seeds, nodes)

	assert out[0].nodes == (20,), f'非错误节点被当成来源：{out[0].nodes}'
