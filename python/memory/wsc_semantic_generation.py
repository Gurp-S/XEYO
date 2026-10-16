"""Natural-language compaction, independent of task-state mutation.

The instruction is the repository's pinned Codex prompt (expanded-208 vendor).
It is used only in the dedicated compactor, never injected into continuation.
Read-only recall is available over a captured snapshot. No HTTP retries;
incomplete output cannot become a checkpoint.
"""

PROMPT = """You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff summary for another LLM that will resume the task.

Include:
- Current progress and key decisions made
- Important context, constraints, or user preferences
- What remains to be done (clear next steps)
- Any critical data, examples, or references needed to continue

Be concise, structured, and focused on helping the next LLM seamlessly continue the work.
"""


async def generate(model, messages, abort, *, account, output_tokens=4096, sources=None,
                   admit_next=None, admit_read=None, guard=None, alternative_messages=None):
    from memory.wsc_handoff_generation import limited_client
    from memory.wsc_semantic_recall import generate as recall
    client = limited_client(model, output_tokens)
    return await recall(client, messages, abort, prompt=PROMPT, sources=sources, account=account,
        output_tokens=output_tokens, context_limit=getattr(model, 'context_limit', None),
        admit_next=admit_next, admit_read=admit_read, guard=guard,
        alternative_messages=alternative_messages)
