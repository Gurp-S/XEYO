// Rebuild the message list one compaction actually saw.
//
// The recorded `tool/result` event is a *harness* event, not an agent message:
// it carries `source: { kind: 'tool', callId }` and a `tool-result` content part
// whose own `content` array holds the text. A replay that pushes the raw event
// payload straight into the checkpoint builder therefore feeds it messages with
// no `role`, and every tool result is silently dropped — which made an earlier
// replay report a deterministic checkpoint as carrying ~1% of its region when
// the cause was the harness, not the builder.
//
// This module does the one normalisation both replays need, so the numbers they
// print describe the builder instead of the recorder.

/** Flatten a `tool-result` part into the text parts an agent message carries. */
const flattenContent = (content) => {
  if (!Array.isArray(content)) return content
  return content.flatMap((part) =>
    part?.type === 'tool-result' && Array.isArray(part.content) ? part.content : [part],
  )
}

/**
 * Normalise one recorded event payload into an agent message.
 *
 * @param {object} event recorded session event.
 * @returns {object | undefined} agent-shaped message, or undefined when the event
 *   carries no message at all.
 */
export function toAgentMessage(event) {
  if (event.type === 'user/message') {
    return { role: 'user', content: event.data.content, source: event.data.source }
  }
  if (event.type !== 'assistant/message' && event.type !== 'tool/result') return undefined
  const message = event.data?.message
  if (message === undefined || message === null) return undefined
  const kind = message.source?.kind
  const role =
    message.role ??
    (kind === 'tool' ? 'tool' : kind === 'assistant' ? 'assistant' : kind === 'user' ? 'user' : undefined)
  return {
    ...message,
    role,
    content: flattenContent(message.content),
    toolCallId: message.toolCallId ?? message.source?.callId,
  }
}

/**
 * Rebuild a shadowed region, in sequence order.
 *
 * @param {ReadonlyArray<object>} events session events.
 * @param {ReadonlyArray<number>} seqs shadowed sequence numbers.
 * @returns {object[]} agent-shaped messages.
 */
export function regionMessages(events, seqs) {
  const bySeq = new Map(events.map((event) => [event.seq, event]))
  const messages = []
  for (const seq of [...seqs].sort((left, right) => left - right)) {
    const event = bySeq.get(seq)
    if (event === undefined) continue
    const message = toAgentMessage(event)
    if (message !== undefined) messages.push(message)
  }
  return messages
}
