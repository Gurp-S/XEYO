import sys

def edit(path, nl, pairs):
    s = open(path, encoding="utf-8", newline="").read()
    for old, new in pairs:
        n = s.count(old)
        if n != 1:
            print(f"!! {path}: match={n} for {old[:50]!r}"); sys.exit(1)
        s = s.replace(old, new)
    open(path, "w", encoding="utf-8", newline="").write(s)
    print("ok:", path)

# ---------- tool_registry.py (tabs) ----------
p = "tools/tool_registry.py"
s = open(p, encoding="utf-8", newline="").read()
nl = "\r\n" if "\r\n" in s else "\n"
pairs = [
    ("import os" + nl, "import logging" + nl + "import os" + nl),
    ("if TYPE_CHECKING:" + nl + "\tfrom engine.permission_coordinator import PermissionCoordinator" + nl,
     "if TYPE_CHECKING:" + nl + "\tfrom engine.permission_coordinator import PermissionCoordinator" + nl + nl + "_log = logging.getLogger(__name__)" + nl),
    ("\texcept Exception:  # noqa: BLE001 — 观测失败绝不挡执行" + nl + "\t\tpass" + nl,
     "\texcept Exception:  # noqa: BLE001 — 观测失败绝不挡执行（debug 留痕，不静默）" + nl + "\t\t_log.debug(\"bash route observe failed\", exc_info=True)" + nl),
]
for old, new in pairs:
    n = s.count(old)
    if n != 1:
        print("!! tool_registry match", n, repr(old[:60])); sys.exit(1)
    s = s.replace(old, new)
open(p, "w", encoding="utf-8", newline="").write(s)
print("ok: tools/tool_registry.py")

# ---------- subagent_runner.py (4 spaces) ----------
p = "engine/subagent_runner.py"
s = open(p, encoding="utf-8", newline="").read()
nl = "\r\n" if "\r\n" in s else "\n"
pairs = [
    ("from pathlib import Path" + nl + "import os" + nl,
     "import logging" + nl + "from pathlib import Path" + nl + "import os" + nl),
    ("DEFAULT_SUB_MAX_TURNS = 32" + nl,
     "_log = logging.getLogger(__name__)" + nl + nl + "DEFAULT_SUB_MAX_TURNS = 32" + nl),
    ("        except Exception:  # noqa: BLE001" + nl + "            pass" + nl + nl +
     "    # 厂商调用前先把本轮用户/续跑触发落盘，避免 403 后侧链缺首条。",
     "        except Exception:  # noqa: BLE001 — 失败不阻断子 agent（debug 留痕）" + nl +
     "            _log.debug(\"subagent live transcript flush failed\", exc_info=True)" + nl + nl +
     "    # 厂商调用前先把本轮用户/续跑触发落盘，避免 403 后侧链缺首条。"),
    ("    except Exception:  # noqa: BLE001" + nl + "        pass" + nl + nl + "    last_flush_mono = 0.0",
     "    except Exception:  # noqa: BLE001 — 失败不阻断子 agent（debug 留痕）" + nl +
     "        _log.debug(\"subagent transcript flush failed\", exc_info=True)" + nl + nl + "    last_flush_mono = 0.0"),
]
for old, new in pairs:
    n = s.count(old)
    if n != 1:
        print("!! subagent_runner match", n, repr(old[:60])); sys.exit(1)
    s = s.replace(old, new)
open(p, "w", encoding="utf-8", newline="").write(s)
print("ok: engine/subagent_runner.py")
