import pathlib

T = "\t"
edits = {
 "python/engine/subagent_runner.py": [
  ('        logging.getLogger(__name__).debug("record_transcript failed", exc_info=True)',
   '        _log.debug("record_transcript failed", exc_info=True)'),
  ('            logging.getLogger(__name__).debug("record_subagent_usage failed", exc_info=True)',
   '            _log.debug("record_subagent_usage failed", exc_info=True)'),
 ],
 "python/tools/tool_registry.py": [
  (T*3 + 'logging.getLogger(__name__).debug("default_audit_log().record failed", exc_info=True)',
   T*3 + '_log.debug("tool.routed audit failed", exc_info=True)'),
 ],
 "python/engine/query_engine.py": [
  ('                        logging.getLogger(__name__).debug("self._rewind_journal.audit failed", exc_info=True)',
   '                        logging.getLogger(__name__).debug(\n                            "rewind failure audit failed", exc_info=True\n                        )'),
  ('                            turn_started_ns=turn_started_ns,\n                            )\n                    except Exception:\n                        pass\n',
   '                            turn_started_ns=turn_started_ns,\n                            )\n                    except Exception:  # noqa: BLE001 — 索引观测失败只留痕\n                        logging.getLogger(__name__).debug(\n                            "rewind index sync failed", exc_info=True\n                        )\n'),
 ],
 "python/engine/query_loop.py": [
  ('        logging.getLogger(__name__).debug("default_audit_log().record failed", exc_info=True)',
   '        logging.getLogger(__name__).debug("llm failure audit failed", exc_info=True)'),
  ('''        def _observe_body() -> None:
            try:
                from memory.observe import observe_shot

                observe_shot(
                    snap,
                    projected,
                    hit=hit,
                    miss=miss,
                    out=out,
                    context_tokens=context_tokens,
                    turn=budget.turn_count,
                    provider=getattr(model, "provider", None),
                    model=getattr(model, "_model", None)
                    or getattr(model, "model", None),
                )
            except Exception:
                logging.getLogger(__name__).debug("observe_shot failed", exc_info=True)

        _observe_task = asyncio.create_task(asyncio.to_thread(_observe_body))

        async def _await_observe() -> None:
            try:
                await _observe_task
            except Exception:
                pass
''',
   '''        def _observe_body() -> None:
            from memory.observe import observe_shot

            # 观测侧一律经 safe_observe 隔离（2026-09-14 事故的结构性防线）：
            # Ĥ / LCP 采样失败只落 debug 日志，绝不进主链路、绝不与防护共 try。
            safe_observe(
                observe_shot,
                snap,
                projected,
                hit=hit,
                miss=miss,
                out=out,
                context_tokens=context_tokens,
                turn=budget.turn_count,
                provider=getattr(model, "provider", None),
                model=getattr(model, "_model", None) or getattr(model, "model", None),
                label="memory.observe.observe_shot",
            )

        _observe_task = asyncio.create_task(asyncio.to_thread(_observe_body))

        async def _await_observe() -> None:
            try:
                await _observe_task
            except Exception:  # noqa: BLE001 — 观测任务失败只留痕
                logging.getLogger(__name__).debug(
                    "observe shot task failed", exc_info=True
                )
'''),
 ],
 "python/engine/title.py": [
  (T*2 + 'logging.getLogger(__name__).debug("default_audit_log().record failed", exc_info=True)',
   T*2 + 'logging.getLogger(__name__).debug("title audit failed", exc_info=True)'),
 ],
 "python/engine/write_store.py": [
  ('            logging.getLogger(__name__).debug("default_session_presence().note_write failed", exc_info=True)',
   '            logging.getLogger(__name__).debug(\n                "session presence note_write failed", exc_info=True\n            )'),
 ],
 "python/engine/scheduler.py": [
  ('                        logging.getLogger(__name__).debug("record_patch_retry failed", exc_info=True)',
   '                        logging.getLogger(__name__).debug(\n                            "patch retry metric failed", exc_info=True\n                        )'),
  ('            logging.getLogger(__name__).debug("record_task_finished failed", exc_info=True)',
   '            logging.getLogger(__name__).debug(\n                "task finished metric failed", exc_info=True\n            )'),
 ],
 "python/tools/agent_tool/agent_tool.py": [
  ('                logging.getLogger(__name__).debug("record_agent_settlement failed", exc_info=True)',
   '                logging.getLogger(__name__).debug(\n                    "record_agent_settlement failed", exc_info=True\n                )'),
  ('                logging.getLogger(__name__).debug("record_agent_tool_end failed", exc_info=True)',
   '                logging.getLogger(__name__).debug(\n                    "record_agent_tool_end failed", exc_info=True\n                )'),
 ],
 "python/tools/bash_tool/bash_tool.py": [
  (T*3 + 'logging.getLogger(__name__).debug("default_session_presence().note_git failed", exc_info=True)',
   T*3 + '_log.debug("session presence note_git failed", exc_info=True)'),
  (T*3 + 'logging.getLogger(__name__).debug("default_session_presence().note_write failed", exc_info=True)',
   T*3 + '_log.debug("session presence note_write failed", exc_info=True)'),
 ],
 "python/tools/notebook_edit_tool/notebook_edit_tool.py": [
  (T*3 + 'logging.getLogger(__name__).debug("rewind_context.record_file_mutation failed", exc_info=True)',
   T*3 + 'logging.getLogger(__name__).debug(\n' + T*4 + '"rewind file mutation note failed", exc_info=True\n' + T*3 + ')'),
 ],
 "python/tools/todo_write_tool/todo_write_tool.py": [
  (T*2 + 'logging.getLogger(__name__).debug("default_session_presence().note_todos failed", exc_info=True)',
   T*2 + 'logging.getLogger(__name__).debug(\n' + T*3 + '"session presence note_todos failed", exc_info=True\n' + T*2 + ')'),
 ],
}

for path, pairs in edits.items():
    p = pathlib.Path(path)
    text = p.read_text(encoding="utf-8")
    for old, new in pairs:
        n = text.count(old)
        assert n == 1, f"{path}: expected 1 match, got {n} for {old[:70]!r}"
        text = text.replace(old, new)
    p.write_text(text, encoding="utf-8")
    print("ok", path)
print("DONE")
