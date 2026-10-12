"""Stable host probes cached separately from task-local permissions."""
def facts(module, cwd):
    key = str(cwd or "").strip()
    cached = module._FACTS_CACHE.get(key)
    if cached is None:
        cached = module.collect(key)
        module._FACTS_CACHE[key] = {k: v for k, v in cached.items()
                                    if k not in {"writable", "scratch", "browser", "syntax"}}
    values = {k: v for k, v in cached.items()
              if k not in {"writable", "scratch", "browser", "syntax"}}
    from engine.execution_facts import writable
    import os
    if key and writable(os.path.join(key, "workspace-probe.txt"), key):
        values["writable"] = module._clip(key)
    # Same predicate as scratch writes, independently of a workspace-root probe.
    scratch = module.probe_scratch(key)
    if scratch:
        values["scratch"] = module._clip(scratch.replace("\\", "/"))
    browser = module.probe_browser()
    if browser:
        values["browser"] = browser
    if module.syntax_fact_enabled():
        from tools.bash_tool.runner import build_shell_argv
        values["syntax"] = ("PowerShell: object pipeline, $ variables, here-string"
                            if build_shell_argv("")[1] in {"pwsh", "powershell"}
                            else "POSIX sh: text pipeline, $ variables, heredoc")
    return values
