import { buildWorkingSet, createWorkingSet } from '../../lib/workingset-v2.js'

const call = (id, name, args) => ({ type: 'tool-call', id, name, arguments: JSON.stringify(args) })
const say = (text) => ({ type: 'text', text })
const asst = (...content) => ({ role: 'assistant', content })
const result = (callId, body) => ({
  role: 'user',
  toolCallId: callId,
  content: [{ type: 'text', text: `<path>x</path>\n<content>\n${body}\n</content>` }],
})

const messages = [
  asst(say('Checking how the planner resolves outputs before editing it.'), call('c1', 'read', { path: 'src/planner.js' })),
  result('c1', 'export const plan = () => 1\nexport const done = () => 2'),
  asst(say('Now rewriting the resolver.'), call('c2', 'edit', { path: 'src/planner.js', old_string: 'export const plan = () => 1', new_string: 'export const plan = () => 42' })),
]

const first = buildWorkingSet(messages)
console.log('--- section ---')
console.log(first.join('\n'))
console.log('--- checks ---')
const text = first.join('\n')
console.log('body kept after edit:', text.includes('export const done = () => 2'))
console.log('role follows latest touch:', text.includes('Now rewriting the resolver.'))
console.log('delta rendered:', /edited #\d+ \(\+\d+\/−\d+\)/.test(text))
console.log('body size:', text.length)

const seed = `## Working set\n\n${text}\n`
const again = buildWorkingSet([], { seed })
console.log('round-trip keeps body:', again.join('\n').includes('export const done = () => 2'))
console.log('round-trip keeps role:', again.join('\n').includes('Now rewriting the resolver.'))
console.log('round-trip keeps delta:', /edited #\d+/.test(again.join('\n')))

const many = []
for (let i = 0; i < 8; i += 1) {
  many.push(asst(say(`Reading file ${i}`), call(`r${i}`, 'read', { path: `f${i}.js` })))
  many.push(result(`r${i}`, 'x'.repeat(1200)))
}
const capped = buildWorkingSet(many)
console.log('capped section chars:', capped.join('\n').length, 'entries:', capped.length)

const tracker = createWorkingSet()
tracker.apply(many)
console.log('tracker size:', tracker.size())
