import { readFileSync } from 'node:fs'

const names = process.argv.slice(2)
const rows = names.map((name) => {
  try {
    return { name, ...JSON.parse(readFileSync(`experiments/report/raw/${name}.json`, 'utf8')) }
  } catch {
    return { name, missing: true }
  }
})

const fmt = (n) => (typeof n === 'number' ? n.toLocaleString('en-US') : '—')
console.log('| run | score | in | out | req | in/req | s |')
console.log('| --- | --- | --- | --- | --- | --- | --- |')
for (const row of rows) {
  if (row.missing) {
    console.log(`| ${row.name} | missing | | | | | |`)
    continue
  }
  const per = row.requests ? Math.round(row.inputTokens / row.requests) : null
  console.log(
    `| ${row.name} | ${row.passed}/${row.total} | ${fmt(row.inputTokens)} | ${fmt(row.outputTokens)} | ${fmt(row.requests)} | ${fmt(per)} | ${row.seconds} |`,
  )
}
