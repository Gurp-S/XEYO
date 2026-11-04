// Generates fixture-hard/HISTORY.md: a frozen prior-session log long enough
// that a production-budget run has to compact at least once.
//
// The log is deterministic: same repo, same output, every time.

import { readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const root = path.resolve(process.argv[2] ?? 'D:/lea/XenYon code/dsh-wsc/experiments/fixture-hard')
const walk = (dir) => readdirSync(dir).flatMap((name) => {
  const full = path.join(dir, name)
  if (name.startsWith('HISTORY.') || name === 'node_modules' || name === '.git') return []
  return statSync(full).isDirectory() ? walk(full) : [full]
})

const narrative = readFileSync(path.join(root, 'HISTORY.seed.md'), 'utf8').trimEnd()

const dump = (file) => {
  const rel = path.relative(root, file).replace(/\\/g, '/')
  const body = readFileSync(file, 'utf8').trimEnd()
  return `### dump ${rel} (${body.split('\n').length} lines)\n\n\`\`\`\n${body}\n\`\`\`\n`
}

// A frozen slice of the finance export the previous session worked against.
const rows = []
for (let index = 0; index < 1500; index += 1) {
  const day = String((index % 28) + 1).padStart(2, '0')
  const category = ['food', 'tools', 'travel', 'office', 'software'][index % 5]
  const whole = 3 + ((index * 7) % 180)
  const cents = String((index * 13) % 100).padStart(2, '0')
  rows.push(`2026-09-${day},${category},${whole},${cents}`)
}
const exportSlice = `### dump exports/2026-09.csv (${rows.length} rows, comma decimals)\n\n\`\`\`\ndate,category,amount\n${rows.join('\n')}\n\`\`\`\n`

const ciLog = (id, status, note) => `### ci ${id}\n\n\`\`\`\nrun ${id}\nstatus ${status}\n${note}\n\`\`\`\n`
const ciEntries = [
  ciLog('rc-1', 'FAILED', 'money.rounding: 3 failing cases\n  parseAmount("12,35") -> 123500 (expected 1235)\n  parseAmount("1.234,56") -> 12345600 (expected 123456)'),
  ciLog('rc-2', 'FAILED', 'money.rounding: 1 failing case\n  parseAmount("1.234,56") -> 12345600 (expected 123456)'),
  ciLog('rc-3', 'PASSED', 'all suites green at 2026-10-30 00:05 UTC'),
]

const body = [
  narrative,
  '',
  '## Archived tool outputs',
  '',
  'Kept verbatim so the next session does not have to re-run anything.',
  '',
  ...walk(root).sort().map(dump),
  exportSlice,
  ...ciEntries,
].join('\n')

writeFileSync(path.join(root, 'HISTORY.md'), `${body}\n`, 'utf8')
console.log('chars', body.length, 'lines', body.split('\n').length)


