"""XEYO FastAPI 服务（OpenAI 兼容 HTTP + SSE）。"""

from __future__ import annotations

# editable 安装只映射 packages.find 里的包；顶层单文件模块（如 media_store）
# 依赖 python 根在 sys.path。用绝对路径钉住，避免进程 cwd 不在 python/ 时导入失败。
import sys
from pathlib import Path

_PYTHON_ROOT = str(Path(__file__).resolve().parent.parent)
if _PYTHON_ROOT not in sys.path:
	sys.path.insert(0, _PYTHON_ROOT)
