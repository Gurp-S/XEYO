"""A thought acknowledgement represents durable transcript rows."""
import asyncio


async def persist_thoughts(rows, *, session_id, known_ids):
    from session.persistence import should_persist, transcript_path
    from session.record_transcript import record_ui_thoughts
    from session.transcript_barrier import flush_path

    if not should_persist():
        raise OSError("transcript persistence disabled")
    written = await record_ui_thoughts(rows, session_id=session_id, known_ids=known_ids)
    if not await asyncio.to_thread(flush_path, transcript_path(session_id)):
        raise OSError("transcript append incomplete")
    return written
