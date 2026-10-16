"""Literal path binding for the supported filesystem cmdlets only."""


def cmdlet_targets(program, tokens):
    paths, positional = [], []
    path_flags = {"-literalpath", "-path", "-filepath"}
    value_flags = {"-value", "-encoding", "-itemtype", "-erroraction", "-warningaction"}
    switches = {"-force", "-recurse", "-append", "-nonewline", "-passthru", "-whatif", "-confirm"}
    i = 1
    while i < len(tokens):
        token = tokens[i]
        low = token.lower()
        if low in path_flags | value_flags:
            if i + 1 == len(tokens) or tokens[i + 1].startswith("-"):
                return None
            if low in path_flags:
                paths.append(tokens[i + 1])
            i += 2
        elif low in switches:
            i += 1
        elif token.startswith("-"):
            return None  # Names, providers and abbreviated parameters need separate proof.
        else:
            positional.append(token)
            i += 1
    if paths:
        return paths if not positional else None
    if program in {"remove-item", "clear-content"}:
        return positional
    return positional if len(positional) == 1 else None
