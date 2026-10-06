"""有归档出口时的日志换头候选；只在明确折叠点调用。"""

from synaptic.handles import renderer_or_default


def journal_preserves_head(previous, params) -> bool:
    """Only a verified full append prefix can replace the archive obligation."""
    return bool(
        params.journal_layout and not params.journal_rebase
        and previous is not None and previous.mode == params.mode and previous.journal
        and previous.full_text == "\n".join(f"{h} {line}" for h, line in previous.journal)
    )


def rebase_journal(fresh, *, old_head_handle: str, handles=None):
    """缺少旧头句柄时保持原策略；旧信息不能因换头失去引用。"""
    if not old_head_handle:
        return None
    renderer = renderer_or_default(handles)
    return tuple(fresh) + (("[HEAD]", f"previous={renderer.expression(old_head_handle)}"),)
