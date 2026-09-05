"""从 registry 生成 GUI / CLI-TS 消费的 manifest TS 模块。

用法（在 ``python/`` 目录下）::

    py -3.11 -m slash.export_manifest

产出（提交到仓库，供各端构建期直接 import，避免跨语言运行时耦合）：
- ``gui/src/generated/slashManifest.ts``
- ``cli-ts/src/generated/slashManifest.ts``

两处内容一致；只换一次身份声明文案。
"""

from __future__ import annotations

import json
from pathlib import Path

from .registry import COMMANDS, SURFACES, Command

_SLASH_PKG_DIR = Path(__file__).resolve().parent
# python/slash -> python -> 仓库根
_REPO_ROOT = _SLASH_PKG_DIR.parents[1]

_OUTPUTS: tuple[tuple[Path, str], ...] = (
	(
		_REPO_ROOT / "gui" / "src" / "generated" / "slashManifest.ts",
		"gui",
	),
	(
		_REPO_ROOT / "cli-ts" / "src" / "generated" / "slashManifest.ts",
		"cli_ts",
	),
)


def _cmd_to_ts(cmd: Command) -> str:
	aliases = ", ".join(f'"{a}"' for a in cmd.aliases)
	surfaces = ", ".join(f'"{s}"' for s in cmd.surfaces)
	return (
		"\t{\n"
		f'\t\tname: "{cmd.name}",\n'
		f'\t\tcategory: "{cmd.category}",\n'
		f'\t\thandler: "{cmd.handler}",\n'
		f'\t\tsummary: {json.dumps(cmd.summary, ensure_ascii=False)},\n'
		f'\t\tusage: {json.dumps(cmd.usage, ensure_ascii=False)},\n'
		f"\t\taliases: [{aliases}],\n"
		f'\t\targ_spec: {json.dumps(cmd.arg_spec, ensure_ascii=False)},\n'
		f"\t\tsurfaces: [{surfaces}],\n"
		f'\t\twhen: "{cmd.when}",\n'
		"\t}"
	)


def _render() -> str:
	entries = ",\n".join(_cmd_to_ts(c) for c in COMMANDS)
	# "gui", "cli", ... -> 每行一个，带缩进
	surface_lines = "".join(f'\t"{s}",\n' for s in SURFACES)
	return (
		"// 本文件由 `python -m slash.export_manifest` 自动生成，请勿手改。\n"
		"// 单一事实源：python/slash/registry.py。\n"
		"// 消费方：GUI Composer 自动补全 / 帮助，与各 CLI Ink 的 typeahead。\n"
		"// 新增命令：改 registry.py 后重跑导出。\n\n"
		"export const SURFACES = [\n"
		f"{surface_lines}"
		"] as const;\n\n"
		"export type SlashCategory =\n"
		'\t| "meta"\n'
		'\t| "session"\n'
		'\t| "mode"\n'
		'\t| "info"\n'
		'\t| "control"\n'
		'\t| "memory"\n'
		'\t| "tool"\n'
		'\t| "extension"\n'
		'\t| "demo";\n\n'
		"export type SlashHandler = \"client\" | \"server\";\n\n"
		"export type SlashCommand = {\n"
		"\tname: string;\n"
		"\tcategory: SlashCategory;\n"
		"\thandler: SlashHandler;\n"
		"\tsummary: string;\n"
		"\tusage: string;\n"
		"\taliases: string[];\n"
		"\targ_spec: string;\n"
		"\tsurfaces: string[];\n"
		'\twhen: "idle" | "always";\n'
		"};\n\n"
		"export const slashCommands: SlashCommand[] = [\n"
		f"{entries},\n"
		"];\n"
	)


def main() -> int:
	import sys

	code = _render()
	if "--check" in sys.argv:
		drift = False
		for path, _surface in _OUTPUTS:
			if not path.is_file():
				print(f"missing {path}")
				drift = True
				continue
			if path.read_text(encoding="utf-8") != code:
				print(f"drift {path} — run: py -3.11 -m slash.export_manifest")
				drift = True
		return 1 if drift else 0

	for path, _surface in _OUTPUTS:
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(code, encoding="utf-8")
		print(f"wrote {path}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
