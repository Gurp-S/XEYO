import io

def split_patch(path):
    lines = io.open(path, encoding="utf-8").read().split("\n")
    head = []
    hunks = []
    cur = None
    for l in lines:
        if l.startswith("@@"):
            if cur is not None: hunks.append(cur)
            cur = [l]
        elif cur is None:
            head.append(l)
        else:
            cur.append(l)
    if cur is not None: hunks.append(cur)
    return head, hunks

def write(path, head, hunks):
    out = head + [l for h in hunks for l in h]
    txt = "\n".join(out)
    if not txt.endswith("\n"): txt += "\n"
    io.open(path, "w", encoding="utf-8", newline="").write(txt)

head, hunks = split_patch("_rt.patch")
keep = [h for h in hunks if "params_for_window" not in "\n".join(h)]
print("rt hunks", len(hunks), "keep", len(keep))
write("_rt_mine.patch", head, keep)

head2, hunks2 = split_patch("_chat.patch")
keep2 = [h for h in hunks2 if "note_request_env" in "\n".join(h)]
print("chat hunks", len(hunks2), "keep", len(keep2))
write("_chat_mine.patch", head2, keep2)
