/**
 * Canonical text projection of a message.
 *
 * Several surfaces show message bytes back to the model: the selection
 * transcript, `read_history`, and `read_evidence`. They must project a message
 * the same way, because a quote is only verifiable when the bytes the model was
 * shown are the bytes the engine searches.
 *
 * Tool results arrive as `user` messages carrying `tool-result` blocks (an
 * assistant `tool-call` is answered by a new user turn). A projection that keeps
 * only `text` blocks therefore drops the entire tool surface: the selection
 * transcript never offers tool output, `read_history` cannot find it, and
 * `read_evidence` returns an empty body for a shadowed tool result.
 *
 * `toolText` controls whether tool results are projected. It defaults to off so
 * the selection surface keeps its previous shape until an A/B run proves that
 * exposing tool output improves the checkpoint.
 */

/** @param {object} block @param {{toolText?: boolean}} options @returns {string} */
export function blockText(block, options = {}) {
  const type = block?.type
  if (type === 'text') return typeof block.text === 'string' ? block.text : ''
  if (type === 'tool-call') {
    // The selection surface shows text only by default; history and evidence
    // reads also show what was called, because the call is the context of the
    // output that follows it.
    if (options.toolCalls !== true) return ''
    const args = typeof block.arguments === 'string' ? block.arguments : JSON.stringify(block.arguments ?? {})
    return `[tool-call ${block.name ?? 'unknown'} ${args}]`
  }
  if (type === 'tool-result') {
    if (options.toolText !== true) return ''
    return toolResultText(block)
  }
  if (type === 'image') return '[image]'
  if (type === 'file') return '[file]'
  // Reasoning and provider-specific blocks are not part of the region's content.
  return ''
}

/** @param {object} block @returns {string} the result body, flattened to text. */
function toolResultText(block) {
  const content = block?.content
  if (typeof content === 'string') return content
  if (Array.isArray(content)) {
    return content
      .map((part) => (typeof part === 'string' ? part : typeof part?.text === 'string' ? part.text : ''))
      .filter((text) => text.length > 0)
      .join('\n')
  }
  if (content === undefined || content === null) return ''
  return JSON.stringify(content)
}

/**
 * @param {object} message
 * @param {{toolText?: boolean}} [options]
 * @returns {string} the message's projected text, blocks joined by newlines.
 */
export function messageText(message, options = {}) {
  const content = message?.content
  if (Array.isArray(content)) {
    return content
      .map((block) => blockText(block, options))
      .filter((text) => text.length > 0)
      .join('\n')
  }
  return typeof content === 'string' ? content : ''
}

/**
 * @param {object} message
 * @returns {boolean} whether the message carries tool output.
 */
export function isToolResult(message) {
  return Array.isArray(message?.content) && message.content.some((block) => block?.type === 'tool-result')
}

/**
 * The tool result a message carries, with the facts a caller needs to bind it.
 *
 * A live region carries tool output as a user-role message holding one
 * `tool-result` block: the call id and the error flag live on the block, and the
 * body is a nested `content` array rather than a `text` block. Reading
 * `block.type === 'text'` at the message level therefore yields an empty body
 * and drops every result — which is what made the working-set section empty in
 * every measured run, and what this accessor exists to prevent.
 *
 * @param {object} message a region message.
 * @returns {{ callId: string, text: string, isError: boolean } | undefined}
 *   the result, or undefined when the message carries none.
 */
export function toolResultOf(message) {
  const blocks = Array.isArray(message?.content) ? message.content : []
  const block = blocks.find((item) => item?.type === 'tool-result')
  const callId = block?.toolCallId ?? message?.toolCallId ?? message?.source?.callId
  if (callId === undefined) return undefined
  return {
    callId,
    text: messageText(message, { toolText: true }),
    isError: block?.isError === true || message?.isError === true,
  }
}
