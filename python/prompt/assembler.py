from __future__ import annotations

import os
from typing import Any, Sequence

from prompt.system_prompt import (

    IDENTITY,

    assemble_system_prompt_parts,

    fetch_system_prompt_parts,

    tool_names_from_registry,

)

DEFAULT_SYSTEM = IDENTITY


class PromptAssembler:
    """把 system + 历史拼成模型 API messages。



    会话级 memo：``(cwd, model, tools, custom, append, date, flags, instr_sig)``

    未变则复用已拼好的左段，避免每轮 submit 重装。

    """

    def __init__(self) -> None:

        self._system_memo: dict[tuple, tuple[str, list[dict]]] = {}

    def build(self, system: str, history: list[dict]) -> list[dict]:

        return [{"role": "system", "content": system}, *history]


    def _memo_key(

            self,

            *,

            cwd: str,

            model: str,

            names: Sequence[str],

            custom_system_prompt: str | None,

            append_system_prompt: str | None,

            include_context_blocks: bool,

            date_iso: str | None,

    ) -> tuple:

        from permissions.policy import side_mode as sidemode

        work = os.path.abspath(os.path.expanduser(cwd or "."))

        try:

            from memory.instruction import instruction_cache_signature

            instr_sig = instruction_cache_signature(work, work)

        except Exception:

            instr_sig = ()

        return (

            work,

            model,

            tuple(names),

            (custom_system_prompt or "").strip(),

            (append_system_prompt or "").strip(),

            bool(include_context_blocks),

            date_iso or "",

            instr_sig,

            # side 模式改写左段内容，必须参与 memo 键防串缓存
            sidemode(),

        )

    async def build_system_parts(

            self,

            *,

            cwd: str,

            model: str,

            tools: Any = None,

            tool_names: Sequence[str] | None = None,

            custom_system_prompt: str | None = None,

            append_system_prompt: str | None = None,

            include_context_blocks: bool = True,

            date_iso: str | None = None,

    ) -> tuple[str, list[dict]]:

        """同 ``build_system`` 但额外返回每段的上下文构成（供用量条分类）。



        返回 ``(system_text, breakdown)``，breakdown 为 ``{category, label, chars}`` 列表。

        """

        names = (

            list(tool_names)

            if tool_names is not None

            else tool_names_from_registry(tools)

        )

        key = self._memo_key(

            cwd=cwd,

            model=model,

            names=names,

            custom_system_prompt=custom_system_prompt,

            append_system_prompt=append_system_prompt,

            include_context_blocks=include_context_blocks,

            date_iso=date_iso,

        )

        hit = self._system_memo.get(key)

        if hit is not None:
            return hit

        parts = await fetch_system_prompt_parts(

            cwd=cwd,

            model=model,

            tool_names=names,

            custom_system_prompt=custom_system_prompt,

            date_iso=date_iso,

        )

        result = assemble_system_prompt_parts(

            parts,

            custom_system_prompt=custom_system_prompt,

            append_system_prompt=append_system_prompt,

            include_context_blocks=include_context_blocks,

        )

        self._system_memo[key] = result

        return result

    async def build_system(

            self,

            *,

            cwd: str,

            model: str,

            tools: Any = None,

            tool_names: Sequence[str] | None = None,

            custom_system_prompt: str | None = None,

            append_system_prompt: str | None = None,

            include_context_blocks: bool = True,

            date_iso: str | None = None,

    ) -> str:

        """submit_message 阶段 ② 调用：fetch parts → 拼最终 system 字符串。



        date_iso 由会话层固化后传入，避免跨天首请求改左段字节。

        """

        text, _breakdown = await self.build_system_parts(

            cwd=cwd,

            model=model,

            tools=tools,

            tool_names=tool_names,

            custom_system_prompt=custom_system_prompt,

            append_system_prompt=append_system_prompt,

            include_context_blocks=include_context_blocks,

            date_iso=date_iso,

        )

        return text
