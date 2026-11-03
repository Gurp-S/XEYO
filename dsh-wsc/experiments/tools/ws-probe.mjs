import { buildSelectiveCheckpoint } from '../../lib/checkpoint.js'

const messages = [
  { role: 'user', content: [{ type: 'text', text: 'build the thing' }] },
  {
    role: 'assistant',
    content: [
      {
        type: 'tool-call',
        id: 't1',
        name: 'read',
        arguments: JSON.stringify({ file_path: 'C:/x/a.js' }),
      },
    ],
  },
  {
    role: 'user',
    toolCallId: 't1',
    content: [
      { type: 'text', text: '<path>C:/x/a.js</path>\n<type>file</type>\n<content>\nconst a=1\nconst b=2\n</content>' },
    ],
  },
]

for (const workingset of [undefined, { capChars: 1200, maxFiles: 8 }, { capChars: 700, maxFiles: 6, sectionCap: 2500, version: 2 }]) {
  const out = buildSelectiveCheckpoint(
    { messages },
    { quotes: ['build the thing'], facts: ['the task is to build the thing'], isCheckpointSource: () => false, payload: {}, workingset },
  )
  console.log(
    `workingset=${workingset === undefined ? 'off' : 'on' + (workingset.version === 2 ? '-v2' : '-v1')} -> out=${out === null ? 'null' : out.text.length + 'B'} hasWS=${out !== null && out.text.includes('## Working set')}`,
  )
  if (out !== null && workingset !== undefined) console.log(out.text.slice(0, 300))
}
