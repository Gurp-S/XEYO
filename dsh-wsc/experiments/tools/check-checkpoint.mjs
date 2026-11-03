// Replay successive compactions and print what each checkpoint would carry.
//
// The k2-2 session showed the failure shape: from the second checkpoint on, the
// text opened with `## Prior checkpoint`, and each round nested the previous one
// one level deeper until 100 % of a checkpoint was echo and no working set ever
// appeared. This runs the same chain through the current builder so the two
// tables can be compared row by row.
import { readSessionEvents } from './read-session.mjs'
import { buildCheckpoint } from '../../lib/checkpoint.js'
import { stripPriorEcho } from '../../lib/payload.js'

const file = process.argv[2]
if (file === undefined) {
  console.error('usage: node check-checkpoint.mjs <session.jsonl.zstd> [rounds] [regionMessages]')
  process.exit(2)
}
const rounds = Number(process.argv[3] ?? 8)
const regionSize = Number(process.argv[4] ?? 30)

const events = readSessionEvents(file)
const messages = []
for (const event of events) {
  const message =
    event.data?.message ??
    event.message ??
    (event.data?.role !== undefined && event.data?.content !== undefined ? event.data : undefined)
  if (message?.role !== undefined && message.content !== undefined) messages.push(message)
}

const found = messages.find(
  (message) =>
    message.role === 'user' &&
    (typeof message.content === 'string' || message.content.some((block) => block.type === 'text')) &&
    (typeof message.content === 'string' ? message.content : message.content.find((block) => block.type === 'text').text)
      .length > 80,
)
// The runtime marks the prompt it accepted with `source.kind: 'user'`; the log
// does not persist that marker, so restore it to replay the engine's view.
const request = found === undefined ? undefined : { ...found, source: { kind: 'user' } }
const requestHead =
  request === undefined
    ? ''
    : (typeof request.content === 'string'
        ? request.content
        : request.content.find((block) => block.type === 'text').text
      ).slice(0, 40)
const tail = messages.slice(-regionSize)

const nested = (text) => (text.match(/^\s*-\s+#{1,6}\s/gm) ?? []).length
const echoShare = (text) => Math.round((1 - stripPriorEcho(text).length / text.length) * 100)
const isCheckpointSource = (source) => source?.kind === 'checkpoint'

console.log('n  raw  echo%  nested  ws  keep  head')
let prior
for (let round = 1; round <= rounds; round += 1) {
  const region = [
    ...(prior === undefined
      ? []
      : [{ role: 'user', content: [{ type: 'text', text: prior }], source: { kind: 'checkpoint' } }]),
    // The prompt is in the region only until the first compaction moves it into
    // the checkpoint; every round after that has to carry it forward.
    ...(request === undefined || prior !== undefined ? [] : [request]),
    ...tail,
  ]
  const built = buildCheckpoint(
    { messages: region },
    {
      isCheckpointSource,
      workingset: { maxFiles: 6, capChars: 700, version: 2, sectionCap: 2500 },
    },
  )
  prior = built.text
  const head = built.text.split('\n')[0].replace(/^#+\s*/, '').slice(0, 34)
  console.log(
    `${round}  ${String(built.text.length).padStart(4)}  ${String(echoShare(built.text)).padStart(3)}%  ` +
      `${nested(built.text)}  ${built.text.includes('## Working set') ? 'y' : 'n'}  ` +
      `${requestHead.length > 0 && built.text.includes(requestHead) ? 'y' : 'n'}  ${head}`,
  )
}
