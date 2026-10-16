"""Literal output redirections; ambiguous shell expansion is not a path proof."""
import os


def split_output_redirects(text: str):
    # (value, original spelling, start, end, is operator)
    tokens = []
    i = 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        start = i
        if text[i] == ">":
            i += 1
            if i < len(text) and text[i] == ">":
                i += 1
            tokens.append((text[start:i], text[start:i], start, i, True))
            continue
        if text[i] in "'\"":
            quote = text[i]
            i += 1
            begin = i
            while i < len(text) and text[i] != quote:
                if quote == '"' and (text[i] in "$`" or (text[i] == "\\" and i + 1 < len(text) and text[i + 1] == '"')):
                    return None
                i += 1
            if i == len(text):
                return None
            value = text[begin:i]
            i += 1
            if i < len(text) and not text[i].isspace() and text[i] != ">":
                return None  # Concatenated/escaped quotes differ between shells.
        else:
            while i < len(text) and not text[i].isspace() and text[i] != ">":
                if text[i] in "'\"<$`(){}[];|&#^%" or (text[i] == "\\" and os.name != "nt"):
                    return None
                i += 1
            value = text[start:i]
        tokens.append((value, text[start:i], start, i, False))

    body, paths = [], []
    i = 0
    while i < len(tokens):
        value, raw, start, end, operator = tokens[i]
        if not operator:
            body.append(tokens[i])
            i += 1
            continue
        if body and body[-1][3] == start and body[-1][0].isdigit():
            body.pop()  # 2>file, but not the literal argument in `echo 2 >file`.
        i += 1
        if i == len(tokens) or tokens[i][4]:
            return None
        target = tokens[i][0]
        if not target or any(c in target for c in "$`*?{},[]^%\r\n"):
            return None
        paths.append(target)
        i += 1
    return " ".join(token[1] for token in body), tuple(paths)


def redirect_command_segments(command: str):
    """Executable tokens for tightening rules, never an automatic allow proof."""
    from permissions.bash_targets import segments
    from permissions.bash_readonly import command_segments
    parts = segments(command)
    if parts is None:
        return []
    result = []
    for part in parts:
        split = split_output_redirects(part)
        if split is None:
            return []
        words, reject = command_segments(split[0])
        if reject:
            return []
        result.extend(words)
    return result
