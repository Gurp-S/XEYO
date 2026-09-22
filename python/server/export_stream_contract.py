"""生成 GUI 消费的流式契约 manifest TS 模块（与 `slash.export_manifest` 同一套路）。

用法（在 ``python/`` 目录下）::

    py -3.11 -m server.export_stream_contract          # 写出
    py -3.11 -m server.export_stream_contract --check  # 只校验，漂移即退出码 1

产出（提交进仓库）：``gui/src/generated/streamContract.ts``
—— 后端改了帧名或请求体枚举却没重导出，CI 的 drift 步即红。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Literal, get_args, get_origin

from server.routers.chat import ChatCompletionRequest
from server.stream_contract import (
	ACCEPT_EVENT_KEYS,
	CHUNK_EVENT_ID_KEY,
	STREAM_EVENT_TYPES,
	XY_ENVELOPE_KEY,
)

_SERVER_DIR = Path(__file__).resolve().parent
# python/server -> python -> 仓库根
_REPO_ROOT = _SERVER_DIR.parents[1]
_OUTPUT = _REPO_ROOT / "gui" / "src" / "generated" / "streamContract.ts"

#: 需要跨语言对齐的请求体字段（都是"少一个取值就整条链路 422"的那种）。
_ENUM_FIELDS: tuple[str, ...] = (
	"provider",
	"agent_mode",
	"output_mode",
	"code_mode",
)


def _literal_values(field_type: object) -> list[str]:
	"""从 `Literal[...] | None` 里取出取值集（顺序稳定）。"""
	bits = get_args(field_type) or (field_type,)
	values: list[str] = []
	for bit in bits:
		if get_origin(bit) is Literal or isinstance(bit, Literal.__class__):  # type: ignore[misc]
			values.extend(str(v) for v in get_args(bit))
	return sorted(set(values))


def _chat_body_enums() -> dict[str, list[str]]:
	fields = ChatCompletionRequest.model_fields
	out: dict[str, list[str]] = {}
	for name in _ENUM_FIELDS:
		field = fields.get(name)
		if field is None:
			continue
		values = _literal_values(field.annotation)
		if values:
			out[name] = values
	return out


def _ts_string_list(values: list[str]) -> str:
	return ", ".join(f'"{v}"' for v in values)


def render_ts() -> str:
	enums = _chat_body_enums()
	lines = [
		"/* eslint-disable */",
		"/* 由 `py -3.11 -m server.export_stream_contract` 生成，请勿手改。",
		"   后端帧名 / 请求体枚举的唯一真相：python/server/stream_contract.py",
		"   与 python/server/routers/chat.py 的模型声明。 */",
		"",
		f'export const XY_ENVELOPE_KEY = "{XY_ENVELOPE_KEY}" as const;',
		f'export const CHUNK_EVENT_ID_KEY = "{CHUNK_EVENT_ID_KEY}" as const;',
		"",
		f"export const STREAM_EVENT_TYPES = [{_ts_string_list(sorted(STREAM_EVENT_TYPES))}] as const;",
		"export type StreamEventType = (typeof STREAM_EVENT_TYPES)[number];",
		"",
		"export const ACCEPT_EVENT_KEYS = {",
	]
	for kind in sorted(ACCEPT_EVENT_KEYS):
		lines.append(
			f"\t{kind}: [{_ts_string_list(sorted(ACCEPT_EVENT_KEYS[kind]))}] as const,"
		)
	lines.extend(
		[
			"} as const;",
			"export type AcceptEventKind = keyof typeof ACCEPT_EVENT_KEYS;",
			"",
			"export const CHAT_BODY_ENUMS = {",
		]
	)
	for name in sorted(enums):
		lines.append(f"\t{name}: [{_ts_string_list(enums[name])}] as const,")
	lines.append("} as const;")
	lines.append("")
	return "\n".join(lines)


def write_output() -> None:
	_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
	_OUTPUT.write_text(render_ts(), encoding="utf-8", newline="\n")


def check_output() -> int:
	if not _OUTPUT.exists():
		print(f"缺失生成物：{_OUTPUT}（先跑 py -3.11 -m server.export_stream_contract）")
		return 1
	current = _OUTPUT.read_text(encoding="utf-8").replace("\r\n", "\n")
	if current != render_ts():
		print(f"流式契约生成物已过期：{_OUTPUT}（重跑 py -3.11 -m server.export_stream_contract）")
		return 1
	return 0


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--check", action="store_true", help="只校验生成物是否漂移")
	args = parser.parse_args(argv)
	if args.check:
		return check_output()
	write_output()
	print(f"wrote {_OUTPUT}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
