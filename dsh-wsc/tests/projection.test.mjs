import assert from 'node:assert/strict'
import test from 'node:test'

import { messageText } from '../lib/projection.js'
import { numberedTranscript } from '../lib/selection.js'

const toolTurn = (body) => ({
  role: 'user',
  content: [{ type: 'tool-result', toolCallId: 'call-1', content: [{ type: 'text', text: body }] }],
})

test('projection: tool results are absent under the shipped projection', () => {
  assert.equal(messageText(toolTurn('2 failed')), '')
})

test('projection: tool results are projected when tool text is enabled', () => {
  assert.equal(messageText(toolTurn('2 failed'), { toolText: true }), '2 failed')
})

test('projection: a string tool result is projected as-is', () => {
  const message = { role: 'user', content: [{ type: 'tool-result', content: 'plain output' }] }
  assert.equal(messageText(message, { toolText: true }), 'plain output')
})

test('projection: tool calls keep their name and arguments', () => {
  const message = { role: 'assistant', content: [{ type: 'tool-call', name: 'bash', arguments: '{"command":"npm test"}' }] }
  assert.equal(messageText(message), '')
  assert.equal(messageText(message, { toolCalls: true }), '[tool-call bash {"command":"npm test"}]')
})

test('projection: the transcript labels a tool turn as tool-result and quotes its body', () => {
  const messages = [{ role: 'user', content: [{ type: 'text', text: 'run the tests' }] }, toolTurn('1 failing: watch mode')]
  const shipped = numberedTranscript(messages)
  assert.equal(shipped.text.includes('1 failing: watch mode'), false)
  assert.equal(shipped.tools, 0)

  const withTools = numberedTranscript(messages, { toolText: true })
  assert.equal(withTools.text.includes('[m2 tool-result]'), true)
  assert.equal(withTools.text.includes('1 failing: watch mode'), true)
  assert.equal(withTools.tools, 1)
  assert.ok(withTools.toolChars > 0)
})
