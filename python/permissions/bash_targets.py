"""Conservative literal write-target proof for supported shell segments."""
from __future__ import annotations
import re
import shlex


def segments(command):
    quote = ""
    start = 0
    out = []
    index = 0
    while index < len(command):
        char = command[index]
        if quote:
            if char == quote:
                if index + 1 < len(command) and command[index + 1] == quote:
                    index += 1
                else:
                    quote = ""
        elif char in "'\"":
            quote = char
        elif char in ";\n|&":
            out.append(command[start:index].strip())
            start = index + 1
        elif char in "$`{}()":
            return None
        index += 1
    if quote:
        return None
    out.append(command[start:].strip())
    return [part for part in out if part]


def targets(command):
    from permissions.policy import _BASH_WRITE_CMD_RX, _BASH_INTERP_RX, _BASH_WRITE_MARK_RX
    parts = segments(command)
    if parts is None:
        return None
    from permissions.literal_redirects import split_output_redirects
    from permissions.bash_readonly import analyze, READONLY, DEV
    out = []
    for part in parts:
        redirected = split_output_redirects(part)
        if redirected is None:
            return None
        part, output_paths = redirected
        out.extend(output_paths)
        try:
            raw = shlex.split(part, posix=False)
        except ValueError:
            return None
        tokens = [token[1:-1] if len(token) >= 2 and token[0] == token[-1] and token[0] in "'\"" else token for token in raw]
        program = tokens[0].lower().rsplit("/", 1)[-1].rsplit("\\", 1)[-1].removesuffix(".exe") if tokens else ""
        if program in {"cd", "chdir", "sl", "set-location", "pushd", "popd", "push-location", "pop-location"}:
            return None
        writes = _BASH_WRITE_CMD_RX.search(part) or (_BASH_INTERP_RX.search(part) and _BASH_WRITE_MARK_RX.search(part))
        if not writes:
            # A shell-state change or unclassified command invalidates the
            # target proof for the rest of the chain.
            if analyze(part).kind not in (READONLY, DEV):
                return None
            continue
        if program in {"set-content", "add-content", "out-file", "new-item", "clear-content", "remove-item"}:
            from permissions.powershell_targets import cmdlet_targets
            found = cmdlet_targets(program, tokens)
        elif program in {"rm", "unlink", "rmdir", "touch", "mkdir"}:
            found = [t for t in tokens[1:] if not t.startswith("-")]
        else:
            # Other interpreters/transforms need their own parser, not a last-token guess.
            return None
        if not found or any(any(c in path for c in "$`*?{},") for path in found):
            return None
        out.extend(found)
    return tuple(dict.fromkeys(out)) if out else None
