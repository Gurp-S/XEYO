"""把 python/ 与 tests/ 加入 sys.path，支持 IDE 直接运行测试文件。"""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
_ROOT = _TESTS.parent

for path in (_ROOT, _TESTS):
	s = str(path)
	if s not in sys.path:
		sys.path.insert(0, s)
