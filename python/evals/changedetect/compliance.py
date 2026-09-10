"""compliance —— 应试性自动扫描（用户红线 R1–R4 的可执行部分）。

红线原文（docs/应试性审查-副作用修复与53号.md）：
  R1 产品受益 —— 只对评测受益的改动 = 应试
  R2 无评测分支 —— `if 容器路由|XEYO_BENCH_MINIMAL|任务名` 才生效 = 应试
  R3 信息纪律 —— 注入引擎无法核实的事实 / 给命令建议的导演文本 = 越界
  R4 收益可证伪 —— 只能靠对标判分器或读 /tests 兑现 = 应试

R1/R4 的完整判定需要人，但 R2 是**纯文本可判定的**，R3 也有很强的文本特征。
这里只扫 diff 的**新增行**，避免把既有代码算进来。

定位：这是"报警器"不是"判官"。命中不等于违规，但每一条命中都必须被解释。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class Hit:
    rule: str
    severity: str  # fail | warn
    pattern: str
    line: str
    where: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "pattern": self.pattern,
            "line": self.line.strip()[:200],
            "where": self.where,
        }


#: (规则, 严重度, 正则, 说明)。只在新增行上匹配。
_RULES: tuple[tuple[str, str, str, str], ...] = (
    (
        "R2",
        "fail",
        r"XEYO_BENCH_MINIMAL",
        "评测专用开关：只允许影响工具集，不得影响信息正确性",
    ),
    (
        "R2",
        "fail",
        r"容器路由|container_rout|harbor_route|in_container\b",
        "评测容器路由分支：产品路径不得因评测环境改变行为",
    ),
    (
        "R2",
        "fail",
        r"\bterminal_bench\b|\btb21\b|\bbench_minimal\b|BENCH_BUILD",
        "评测环境识别：任何 `if 评测` 分支都是应试",
    ),
    (
        "R2",
        "warn",
        r"if\s+.*\b(task_id|task_name|任务名)\b\s*==?",
        "按任务名分支：收益只对这道题成立 = 应试",
    ),
    (
        "R4",
        "fail",
        r"\b(?:read|open|load|glob|ls|cat|read_text|readlines|json\.load|pickle\.load)\b[^;\n]*/tests?[\"']?",
        "读取判分器/测试目录兑现：收益不可迁移到产品",
    ),
    (
        "R4",
        "warn",
        r"(?:^|\W)/tests?\b",
        "提及 /tests 路径：核对是否在读判分器/测试",
    ),
    (
        "R3",
        "warn",
        r"你应该|请务必|建议你|不要再|优先(?:选择|使用)|必须(?:先|要)",
        "模型可见文本里的导演型措辞：注意力里只应出现信息",
    ),
)


def scan_added_lines(diff_text: str) -> list[Hit]:
    """扫描 diff 的新增行（`+` 开头且不是 `+++` 头）。"""
    hits: list[Hit] = []
    where = ""
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            where = raw[4:].strip()
            continue
        if not raw.startswith("+") or raw.startswith("+++"):
            continue
        line = raw[1:]
        for rule, severity, pattern, why in _RULES:
            if re.search(pattern, line, flags=re.IGNORECASE):
                hits.append(
                    Hit(
                        rule=rule,
                        severity=severity,
                        pattern=f"{pattern}  —— {why}",
                        line=line,
                        where=where,
                    )
                )
    return hits


def summarize(hits: list[Hit]) -> dict[str, Any]:
    by_rule: dict[str, int] = {}
    by_sev: dict[str, int] = {}
    for h in hits:
        by_rule[h.rule] = by_rule.get(h.rule, 0) + 1
        by_sev[h.severity] = by_sev.get(h.severity, 0) + 1
    return {
        "hit_count": len(hits),
        "by_rule": by_rule,
        "by_severity": by_sev,
        "has_fail": by_sev.get("fail", 0) > 0,
        "hits": [h.to_dict() for h in hits],
    }


def scan_git_diff(paths: list[str] | None = None, *, root=None) -> dict[str, Any]:
    """对工作树 diff 跑一次扫描（读多写无）。"""
    import subprocess

    from .canon import REPO_ROOT

    cmd = ["git", "-c", "core.quotepath=false", "diff", "--no-color", "--unified=0"]
    if paths:
        cmd += ["--", *paths]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root or REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except Exception as exc:  # noqa: BLE001
        return {"hit_count": 0, "error": f"{type(exc).__name__}: {exc}", "hits": []}
    if proc.returncode != 0:
        return {
            "hit_count": 0,
            "error": (proc.stderr or "").strip()[:300],
            "hits": [],
        }
    return summarize(scan_added_lines(proc.stdout))
