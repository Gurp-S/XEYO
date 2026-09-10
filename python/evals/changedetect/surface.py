"""surface —— L0：模型可见文本面（字节级快照）。

覆盖对象是**一切会被写进模型注意力的静态文本**：
  system   身份段 / 环境段 / 围栏段 / 组装结果
  tools    每个工具的 schema（模型靠它决定调什么、怎么传参）
  tnow     T_now 块登记表 + 各静态块的渲染文本 + 块数硬顶
  slash    斜杠命令 manifest（GUI / TUI 两份生成物）

为什么这一层能做到"完美侦测"：这一层里没有模型、没有网络、没有随机数。
同一个字符 → 同一串字节 → 同一个 sha256。改动哪怕一个字符，golden 比对
必然不同，且能精确指出是哪一行。灵敏度 = 1 字节，噪声 = 0，成本 = 0。

反面：它只能证明"注意到了变化"，不能证明"变化是好事"。后者是 L2 的活。
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import canon

GOLDEN_DIR = Path(__file__).resolve().parent / "goldens"
SURFACE_DIR = GOLDEN_DIR / "surface"
INDEX_PATH = GOLDEN_DIR / "surface_index.json"

#: 固定合成输入：让 golden 不随仓库内容漂移（XEYO.md 是用户资产，天天改）
_SYNTH_INSTRUCTIONS = (
    "# 合成指令（changedetect 固定输入，勿改）\n"
    "- 这是快照用的稳定样本，不读真实 XEYO.md。\n"
    "- 改动本段会改变 golden，属于预期行为。\n"
)
_SYNTH_CUSTOM = "自定义 system 段（changedetect 固定输入）。\n"


@dataclass
class Artifact:
    """一段模型可见文本。"""

    name: str
    text: str
    group: str
    note: str = ""

    @property
    def canonical(self) -> str:
        return canon.canon_text(self.text)

    @property
    def sha(self) -> str:
        return canon.sha(self.canonical)


@dataclass
class Change:
    """一处差异。"""

    name: str
    status: str  # added | removed | modified
    group: str = ""
    chars_before: int = 0
    chars_after: int = 0
    added: int = 0
    removed: int = 0
    first_line: int | None = None
    diff: str = ""
    blurb: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "group": self.group,
            "chars_before": self.chars_before,
            "chars_after": self.chars_after,
            "added": self.added,
            "removed": self.removed,
            "first_line": self.first_line,
            "blurb": self.blurb,
            "diff": self.diff,
        }


# --------------------------------------------------------------------------
# 收集器
# --------------------------------------------------------------------------


@contextmanager
def _pinned_env():
    """把影响模型可见文本的环境变量钉死，避免 golden 随开发机环境漂移。"""
    keys = ("XEYO_BENCH_MINIMAL", "XEYO_T_NOW_STRATEGY", "XEYO_T_NOW_SKIP")
    saved = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ.pop(k, None)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _collect_system() -> list[Artifact]:
    from prompt.system_prompt import (
        SystemPromptParts,
        assemble_system_prompt_parts,
        get_default_system_prompt_parts,
    )

    parts = get_default_system_prompt_parts(
        cwd="<CWD>",
        model="<MODEL>",
        tool_names=["Read", "Write", "Bash"],
    )
    out: list[Artifact] = []
    labels = ("system/identity", "system/env", "system/fence")
    for i, text in enumerate(parts):
        label = labels[i] if i < len(labels) else f"system/part{i}"
        out.append(Artifact(label, text, "system"))

    bundled = SystemPromptParts(
        default_system_prompt=list(parts),
        user_context={"instructions": _SYNTH_INSTRUCTIONS},
        system_context={},
    )
    assembled, _breakdown = assemble_system_prompt_parts(bundled)
    out.append(Artifact("system/assembled", assembled, "system"))

    with_extras, _ = assemble_system_prompt_parts(
        bundled, custom_system_prompt=_SYNTH_CUSTOM
    )
    out.append(Artifact("system/assembled_with_custom", with_extras, "system"))
    return out


def _collect_tools() -> list[Artifact]:
    """工具 schema 面。每个工具一个 artifact——改一个工具的说明就是改一个文件。"""
    from tools.catalog import build_default_registry

    out: list[Artifact] = []

    with _pinned_env():
        registry = build_default_registry(cwd="<CWD>")
        schemas = list(registry.schemas())

    by_name = sorted(
        (s for s in schemas if isinstance(s, dict) and s.get("name")),
        key=lambda s: str(s["name"]),
    )
    names = [str(s["name"]) for s in by_name]
    out.append(
        Artifact("tools/_index", "\n".join(names) + "\n", "tools",
                 note="工具名清单（模型可见面）")
    )
    out.append(
        Artifact("tools/_count", str(len(names)) + "\n", "tools")
    )
    for schema in by_name:
        out.append(
            Artifact(
                f"tools/{schema['name']}",
                canon.canon_obj(schema) + "\n",
                "tools",
                note="工具 schema（决定模型怎么调）",
            )
        )

    # bench-minimal 是独立的可见面，单独钉住
    os.environ["XEYO_BENCH_MINIMAL"] = "1"
    try:
        mini = build_default_registry(cwd="<CWD>")
        mini_names = sorted(
            str(s.get("name"))
            for s in mini.schemas()
            if isinstance(s, dict) and s.get("name")
        )
    finally:
        os.environ.pop("XEYO_BENCH_MINIMAL", None)
    out.append(
        Artifact(
            "tools/_bench_minimal_names",
            "\n".join(mini_names) + "\n",
            "tools",
            note="XEYO_BENCH_MINIMAL=1 时的工具集（评测口径红线）",
        )
    )
    return out


#: T_now 静态块渲染器：(artifact 名, 模块属性名, 调用参数)
_TNOW_STATIC: tuple[tuple[str, str, tuple[Any, ...]], ...] = (
    ("tnow/block/wrap_up", "_wrap_up_block_text", ()),
    ("tnow/block/output_compact", "output_compact_block", ()),
    ("tnow/block/code_compact", "code_compact_block", ()),
    ("tnow/block/compact", "compact_block", ()),
    ("tnow/block/browser_preview", "browser_preview_block", ()),
    ("tnow/block/pending_jobs", "pending_jobs_block", ()),
    ("tnow/block/runtime_mode_snapshot", "runtime_mode_snapshot_block", ("<SID>",)),
)


def _collect_tnow() -> list[Artifact]:
    from prompt import pre_llm_inject as inj

    out: list[Artifact] = []
    registry = inj.T_NOW_BLOCK_REGISTRY
    table = "\n".join(
        f"{name}\t{meta.get('klass', '')}\t{meta.get('why', '')}"
        for name, meta in sorted(registry.items())
    )
    out.append(
        Artifact("tnow/registry", table + "\n", "tnow",
                 note="块登记表（加块必须登记，机器执法）")
    )
    out.append(Artifact("tnow/hard_cap", f"{inj.T_NOW_BLOCK_HARD_CAP}\n", "tnow"))
    out.append(
        Artifact(
            "tnow/block_count",
            f"{len(registry)}\n",
            "tnow",
            note="登记块数（与硬顶一起决定准入）",
        )
    )
    for name, attr, args in _TNOW_STATIC:
        try:
            text = str(getattr(inj, attr)(*args))
        except Exception as exc:  # noqa: BLE001 — 渲染失败本身也是可见面变化
            text = f"<render-error {type(exc).__name__}: {exc}>"
        out.append(Artifact(name, text, "tnow"))
    return out


def _collect_slash() -> list[Artifact]:
    out: list[Artifact] = []
    for label, rel in (
        ("slash/gui_manifest", "gui/src/generated/slashManifest.ts"),
        ("slash/tui_manifest", "tui/src/generated/slashManifest.ts"),
    ):
        path = canon.REPO_ROOT / rel
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
        else:
            text = f"<missing: {rel}>"
        out.append(Artifact(label, text, "slash"))
    return out


def _collect_evals_meta() -> list[Artifact]:
    """把侦测器自己的口径也钉住——登记表漂移同样要被侦测。"""
    from . import stats

    rows = stats.power_table()
    body = "\n".join(
        f"{r['discordant_rate']:.2f}\t{r['effect']:.2f}\t{r['required_pairs']}"
        for r in rows
    )
    return [Artifact("meta/power_table", body + "\n", "meta")]


COLLECTORS = (
    _collect_system,
    _collect_tools,
    _collect_tnow,
    _collect_slash,
    _collect_evals_meta,
)


def collect(groups: set[str] | None = None) -> list[Artifact]:
    """渲染全部模型可见文本面。确定性：同样的代码必得同样的字节。"""
    out: list[Artifact] = []
    for collector in COLLECTORS:
        for art in collector():
            if groups and art.group not in groups:
                continue
            out.append(art)
    out.sort(key=lambda a: a.name)
    return out


# --------------------------------------------------------------------------
# golden 读写与比对
# --------------------------------------------------------------------------


def _index_entry(art: Artifact) -> dict[str, Any]:
    return {
        "group": art.group,
        "sha256": art.sha,
        "chars": len(art.canonical),
        "note": art.note,
        "file": f"{canon.safe_name(art.name)}.txt",
    }


def write_golden(arts: list[Artifact], *, directory: Path = GOLDEN_DIR) -> Path:
    surface = directory / "surface"
    surface.mkdir(parents=True, exist_ok=True)
    existing = {p.name for p in surface.glob("*.txt")}
    index: dict[str, Any] = {}
    for art in arts:
        fname = f"{canon.safe_name(art.name)}.txt"
        (surface / fname).write_text(art.canonical, encoding="utf-8", newline="\n")
        existing.discard(fname)
        index[art.name] = _index_entry(art)
    for stale in existing:
        (surface / stale).unlink()
    payload = {
        "schema": 1,
        "generated_by": "evals.changedetect.surface",
        "artifact_count": len(index),
        "artifacts": index,
    }
    path = directory / "surface_index.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def load_golden(*, directory: Path = GOLDEN_DIR) -> dict[str, str]:
    """读回 golden 全文（name → 规范化文本）。"""
    surface = directory / "surface"
    if not surface.is_dir():
        return {}
    out: dict[str, str] = {}
    for path in sorted(surface.glob("*.txt")):
        out[path.stem] = path.read_text(encoding="utf-8")
    return out


def compare(
    arts: list[Artifact],
    *,
    directory: Path = GOLDEN_DIR,
    max_diff_chars: int = 4000,
) -> list[Change]:
    """当前渲染 vs golden，返回全部差异（含 unified diff）。"""
    golden = load_golden(directory=directory)
    current = {canon.safe_name(a.name): a for a in arts}
    # 名称 → artifact 映射（golden 侧只有文件名）
    golden_names = set(golden)
    changes: list[Change] = []

    for key, art in sorted(current.items()):
        before = golden.get(key)
        after = art.canonical
        if before is None:
            changes.append(
                Change(
                    name=art.name,
                    status="added",
                    group=art.group,
                    chars_after=len(after),
                    blurb="新增模型可见文本（golden 中不存在）",
                )
            )
            continue
        if before == after:
            continue
        added, removed = canon.char_delta(before, after)
        changes.append(
            Change(
                name=art.name,
                status="modified",
                group=art.group,
                chars_before=len(before),
                chars_after=len(after),
                added=added,
                removed=removed,
                first_line=canon.first_diff_line(before, after),
                diff=canon.shorten(
                    canon.unified(before, after, art.name), max_diff_chars
                ),
                blurb=art.note,
            )
        )

    for key in sorted(golden_names - set(current)):
        before = golden[key]
        changes.append(
            Change(
                name=key,
                status="removed",
                chars_before=len(before),
                blurb="golden 中存在而当前已消失（文本被删除或改名）",
            )
        )
    return changes


def render_index(arts: list[Artifact]) -> str:
    lines = [
        f"{a.group:<8} {a.sha[:12]}  {len(a.canonical):>8}  {a.name}"
        for a in arts
    ]
    return "\n".join(lines) + "\n"


def summarize(changes: list[Change]) -> dict[str, Any]:
    by_group: dict[str, int] = {}
    for ch in changes:
        by_group[ch.group or "-"] = by_group.get(ch.group or "-", 0) + 1
    return {
        "changed": bool(changes),
        "count": len(changes),
        "by_group": by_group,
        "names": [ch.name for ch in changes],
        "added_chars": sum(ch.added for ch in changes),
        "removed_chars": sum(ch.removed for ch in changes),
    }


# --------------------------------------------------------------------------
# 灵敏度自证
# --------------------------------------------------------------------------


def mutation_selftest(*, probe_chars: int = 1) -> dict[str, Any]:
    """把每个 artifact 改动 probe_chars 个字符，断言 100% 被检出。

    这是"完美侦测"的唯一诚实证明方式：不是声明，而是穷举自测。
    """
    arts = collect()
    total = 0
    missed: list[str] = []
    for art in arts:
        text = art.canonical
        if not text:
            continue
        total += 1
        idx = max(0, len(text) // 2)
        mutated = text[:idx] + ("Z" if text[idx] != "Z" else "Y") + text[idx + 1 :]
        if canon.sha(mutated) == canon.sha(text):
            missed.append(art.name)
    return {
        "probed": total,
        "detected": total - len(missed),
        "missed": missed,
        "sensitivity": "1 字符" if probe_chars == 1 else f"{probe_chars} 字符",
        "perfect": not missed and total > 0,
    }
