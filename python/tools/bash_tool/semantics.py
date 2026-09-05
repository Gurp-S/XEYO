"""退出码语义。非安全边界。"""

from __future__ import annotations
import re

# (is_error_if_code_fn) — 用表驱动更清晰
# code -> (是否错误, 可选消息)


def _split_segment(cmd:str )-> list[str]:
    """轻量拆分 && | ; —— 不用于安全"""
    parts = re.split(r"\s*(?:&&|\|\||[|;])\s*", cmd)
    return [p for p in parts if p and p.strip()]

def extract_base_command(cmd: str) -> str:
    """取决定 exit code 的最后一段的第一个 token。"""
    segments = _split_segment(cmd)
    last = segments[-1] if segments else cmd
    token = last.strip().split()[0] if last.strip() else ""
    if "/" in token or "\\" in token:
        token = token.replace("\\", "/").rsplit("/", 1)[-1]
    if token.lower().endswith(".exe"):
        token = token[:-4]
    return token.lower()


def _git_subcommand(cmd: str) -> str:
    """取 git 子命令；跳过全局选项及带独立值的（-C <dir> / -c <cfg>）。"""
    segments = _split_segment(cmd)
    last = segments[-1] if segments else cmd
    tokens = last.strip().split()
    skip_next = False
    for tok in tokens[1:]:
        if skip_next:
            skip_next = False
            continue
        if tok.startswith("-"):
            if tok in ("-C", "-c"):
                skip_next = True
            continue
        return tok.lower()
    return ""


def interpret_command_result(
    command: str,
    exit_code: int,
) -> tuple[bool, str | None]:
    """
    返回 (is_error, message)。
    message 仅在非致命特殊码时给解释（如 No matches found）。
    """
    base = extract_base_command(command)

    # --- 特殊命令 ---
    if base in ("grep", "rg"):
        # 0=有匹配, 1=无匹配, >=2=真错
        if exit_code == 0:
            return False, None
        if exit_code == 1:
            return False, "No matches found"
        return True, f"Command failed with exit code {exit_code}"

    if base == "git":
        # 只有"1=有产出"语义的子命令放行；merge/rebase/apply 等的 1 仍是
        # 真失败，走默认分支。
        sub = _git_subcommand(command)
        if exit_code == 0:
            return False, None
        if exit_code == 1 and sub == "diff":
            return False, "Differences found"
        if exit_code == 1 and sub == "grep":
            return False, "No matches found"
        return True, f"Command failed with exit code {exit_code}"

    if base == "diff":
        if exit_code == 0:
            return False, None
        if exit_code == 1:
            return False, "Files differ"
        return True, f"Command failed with exit code {exit_code}"

    if base == "find":
        if exit_code == 0:
            return False, None
        if exit_code == 1:
            return False, "Some directories were inaccessible"
        return True, f"Command failed with exit code {exit_code}"

    if base in ("test", "["):
        if exit_code == 0:
            return False, None
        if exit_code == 1:
            return False, "Condition is false"
        return True, f"Command failed with exit code {exit_code}"

    # --- 默认 ---
    if exit_code == 0:
        return False, None
    return True, f"Command failed with exit code {exit_code}"