"""content_index_cache_shadow — 【侧挂模块·默认关】per-file 内容哈希缓存 trigram 贡献。

依据：计划 `docs/实施计划/46-cursor博客技术融合优化计划.md` §B2（⑧）。
对应方案稿：`docs/设计/cursor博客的技术融合到XEYO.md` §⑧（按内容哈希缓存的 per-file 索引层）。

## 为什么（收益目标 — 诚实口径：省 CPU，非省 IO）
- `tools/fileio/content_index.py` 的 `_build_index` 每次 TTL 过期都全量 `_trigrams`（每个文件
  的全文 → 巨大 set 生成，CPU/内存开销大）。
- **必须明确**：要拿到「文件内容哈希」必须先读文件。因此本模块**每次重建仍会读每个文件**，
  缓存命中只跳过**「重算 trigram set」**这一步。所以收益是**省 CPU**（未变文件不重跑 `_trigrams`），
  **不是省 IO**。真正省 IO 由 B3（`content_index_fp_shadow.py` 目录聚合指纹，跳过未变目录的
  整目录读取）承担。
- 内容哈希用 blake2b（同 `codeindex.symbols`），不依赖 mtime（规避 Windows 同秒粗粒度）。

## 侧挂契约（不改主文件逻辑）
- `enabled()`：读 `XEYO_CONTENT_INDEX_CACHE`（默认 0=关）。开=`_build_index` 换成缓存版；
  关=原逻辑（逐位不变）。
- `install()` / `uninstall()`：挂钩 `content_index._build_index`。卸载即恢复原函数。
- **fail-open**：读/哈希任何异常 → 与原文一致（返回 `None`，调用方回退全量 `rg`）。
- **结果一致性**：缓存只决定「是否重算 trigram」，命中时拿回同一 `text→trigrams` 产物，
  `ContentIndex` 与原文逐位等价（超集/上限/bailout 语义全保）。

## 代价探针
- 模块级 `READ_COUNT` 计数「**实际重算 trigram** 的文件数」（命中缓存不计）；`reset_read_count()`
  / `read_count()`。测试：未变文件二建 `READ_COUNT=0`（全命中缓存，省 CPU）；内容改变则递增。
  注意：文件本身仍被读取（为算哈希），故该计数测的是 CPU 省量，不是 IO。
"""

from __future__ import annotations

import hashlib
import importlib
import threading

_TARGET_MODULE = "tools.fileio.content_index"
_HOOK_NAME = "_build_index"
_ENV = "XEYO_CONTENT_INDEX_CACHE"

_ORIG_NAME = "_ORIG__build_index"
_INSTALLED_FLAG = "__content_index_cache_installed"

#: 全局 per-file 缓存：{绝对路径: (content_hash, tuple(trigram))}。
#: 进程内（跨 TTL/build）复用；根在不同 build 间一致时命中。
_CACHE: dict[str, tuple[str, tuple[str, ...]]] = {}
_CACHE_LOCK = threading.Lock()

#: 读代价计数（命中缓存则不计）。
READ_COUNT = 0
_TARGET = None


def enabled() -> bool:
    """是否启用内容哈希缓存（升格后默认开；专用 env / 全局 promote 可关）。"""
    from sidecar.policy import side_enabled

    return side_enabled(_ENV)


def reset_read_count() -> None:
    global READ_COUNT
    READ_COUNT = 0


def read_count() -> int:
    return READ_COUNT


def _hash_text(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8", "replace"), digest_size=16).hexdigest()


def install() -> bool:
    """挂钩 `content_index._build_index`；返回是否实际安装（仅已启用才装）。"""
    if not enabled():
        return False
    global _TARGET
    mod = importlib.import_module(_TARGET_MODULE)
    if not getattr(mod, _INSTALLED_FLAG, False):
        if not hasattr(mod, _ORIG_NAME):
            setattr(mod, _ORIG_NAME, getattr(mod, _HOOK_NAME))
        setattr(mod, _HOOK_NAME, _build_index_cached)
        setattr(mod, _INSTALLED_FLAG, True)
    _TARGET = mod
    return True


def uninstall() -> None:
    global _TARGET
    mod = _TARGET or importlib.import_module(_TARGET_MODULE)
    if getattr(mod, _INSTALLED_FLAG, False):
        setattr(mod, _HOOK_NAME, getattr(mod, _ORIG_NAME))
        setattr(mod, _INSTALLED_FLAG, False)
    _TARGET = None


def _build_index_cached(root: str):
    """缓存版 `_build_index`：未变文件命中缓存，不再重读/重哈希。

    与原文逐位等价（返回 `ContentIndex | None`）；差异只在「是否重读文件」。
    """
    global READ_COUNT
    mod = _TARGET or importlib.import_module(_TARGET_MODULE)

    all_files = mod._list_roots_files(root)
    if all_files is None or len(all_files) > mod._MAX_INDEXED_FILES:
        return None

    trigrams: dict[str, set[str]] = {}
    files: list[str] = []
    total_bytes = 0
    for rel in all_files:
        norm = rel.replace("\\", "/")
        files.append(norm)
        full = __import__("os").path.join(root, rel)
        try:
            size = __import__("os").path.getsize(full)
        except OSError:
            return None
        if size > mod._SKIP_FILE_BYTES:
            return None
        total_bytes += size
        if total_bytes > mod._MAX_INDEXED_BYTES:
            return None

        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            return None

        # 内容哈希：命中缓存且未变 → 复用；否则重读重算。
        digest = _hash_text(text)
        with _CACHE_LOCK:
            cached = _CACHE.get(full)
        if cached is not None and cached[0] == digest:
            file_tgs = cached[1]
        else:
            READ_COUNT += 1
            file_tgs = tuple(mod._trigrams(text))
            with _CACHE_LOCK:
                _CACHE[full] = (digest, file_tgs)

        for tg in file_tgs:
            trigrams.setdefault(tg, set()).add(norm)

    return mod.ContentIndex(root, dict(trigrams), files)
