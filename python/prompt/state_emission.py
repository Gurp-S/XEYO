"""Select current historical state while preserving native event rendering."""
from prompt.notice_channel import wrap_notice


def current_notes(tagged, strategy):
    if strategy not in ("notice_fragment", "system_channel"):
        return {}
    return {key: {"role": "user" if strategy == "notice_fragment" else "system",
                  "content": wrap_notice(text, key) if strategy == "notice_fragment" else text}
            for key, text in tagged if key == "world_state"}


def select_rendered_state(base, rendered, current, strategy):
    if strategy not in ("notice_fragment", "system_channel", "env_channel", "skip"):
        raise ValueError("carrier not validated for append source")
    # 观测：同一 note_key 带多个不同版本 = "同一事实的两个测量值"并存（本场实测
    # world_state 成对出现）。冻结治因，这里把它变成可数事实（指标绝不阻断装配）。
    from prompt.note_duplicates import observe

    observe(rendered, where="select_rendered_state")
    current = current if strategy in ("notice_fragment", "system_channel") else {}
    marked = [{**row, "note_key": "world_state"}
              if strategy == "notice_fragment" and i >= len(base) and "world_state" in current and
                 row.get("role") == "user" and
                 row.get("content") == current["world_state"]["content"] else row
              for i, row in enumerate(rendered)]
    last = {row["note_key"]: i for i, row in enumerate(marked) if row.get("note_key")}
    return [row for i, row in enumerate(marked) if not row.get("note_key") or
            (last[row["note_key"]] == i and row["note_key"] in current and
             row.get("role") == current[row["note_key"]]["role"] and
             row.get("content") == current[row["note_key"]]["content"])]
