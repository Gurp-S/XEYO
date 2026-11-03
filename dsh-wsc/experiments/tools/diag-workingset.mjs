// Replay a session log and ask the working-set builder what it sees.
//
// Answers one question offline: when the engine hands the region to
// `buildWorkingSet`, does it find read calls and their results? A run that
// compacts without a `## Working set` section is either not receiving those
// messages or not recognising their shape, and this separates the two.
import { readSessionEvents } from './read-session.mjs'
import { buildWorkingSet } from '../../lib/workingset-v2.js'

const file = process.argv[2]
if (file === undefined) {
  console.error('usage: node diag-workingset.mjs <session.jsonl.zstd>')
  process.exit(2)
}

const events = readSessionEvents(file)
const types = {}
for (const event of events) types[event.type ?? '?'] = (types[event.type ?? '?'] ?? 0) + 1
console.log('event types:', JSON.stringify(types))

// Collect every message-shaped payload the log carries, in order.
const messages = []
for (const event of events) {
  const message =
    event.data?.message ??
    event.message ??
    (event.data?.role !== undefined && event.data?.content !== undefined ? event.data : undefined)
  if (message?.role !== undefined && message.content !== undefined) messages.push(message)
}
console.log('messages:', messages.length)

const blockTypes = {}
const callNames = {}
for (const message of messages) {
  const blocks = Array.isArray(message.content) ? message.content : []
  for (const block of blocks) {
    const key = `${message.role}/${block.type}`
    blockTypes[key] = (blockTypes[key] ?? 0) + 1
    if (block.type === 'tool-call') callNames[block.name] = (callNames[block.name] ?? 0) + 1
  }
}
console.log('blocks:', JSON.stringify(blockTypes))
console.log('tool calls:', JSON.stringify(callNames))

const withCallId = messages.filter((message) => message.toolCallId !== undefined).length
console.log('messages carrying toolCallId:', withCallId)

const sample = messages.find((message) => message.toolCallId !== undefined)
if (sample !== undefined) {
  console.log('sample result message:', JSON.stringify(sample).slice(0, 400))
}
const sampleCall = messages
  .flatMap((message) => (Array.isArray(message.content) ? message.content : []))
  .find((block) => block.type === 'tool-call')
if (sampleCall !== undefined) console.log('sample call block:', JSON.stringify(sampleCall).slice(0, 300))

const settings = { maxFiles: 6, capChars: 700, version: 2, sectionCap: 2500 }
const items = buildWorkingSet(messages, settings)
console.log('working set items:', items.length)
for (const item of items) console.log('---', item.slice(0, 220))
