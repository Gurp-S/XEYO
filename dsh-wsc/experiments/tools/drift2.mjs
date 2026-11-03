import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import zlib from 'node:zlib'

const M = Buffer.from([0x28, 0xb5, 0x2f, 0xfd])
const frames = (b) => {
  const s = []
  for (let i = 0; i + 4 <= b.length; i++) if (b.compare(M, 0, 4, i, i + 4) === 0) s.push(i)
  const out = []
  for (let k = 0; k < s.length; k++) {
    const end = k + 1 < s.length ? s[k + 1] : b.length
    try { out.push(zlib.zstdDecompressSync(b.subarray(s[k], end)).toString('utf8')) } catch {}
  }
  return out
}
const base = path.join(os.homedir(), '.dsh', 'sessions')
const load = (run) => {
  const dir = fs.readdirSync(base).find((d) => d.includes('runs-' + run + '--'))
  const walk = (p) => {
    for (const e of fs.readdirSync(p, { withFileTypes: true })) {
      const q = path.join(p, e.name)
      if (e.isDirectory()) { const h = walk(q); if (h) return h } else if (e.name.endsWith('.zstd')) return q
    }
    return null
  }
  return frames(fs.readFileSync(walk(path.join(base, dir)))).join('').split(/\r?\n/)
    .filter((l) => l.trim()).map((l) => { try { return JSON.parse(l) } catch { return null } }).filter(Boolean)
}
const short = (p) => String(p ?? '').replace(/\\/g, '/').split('/').slice(-2).join('/')
const calls = (events) => events.filter((e) => e.type === 'tool/call').map((e) => {
  let args = {}
  try { args = JSON.parse(e.data.arguments ?? '{}') } catch {}
  return { name: e.data.name, path: short(args.path ?? args.file_path ?? args.filePath ?? ''), cmd: String(args.command ?? '') }
})

for (const run of process.argv.slice(2)) {
  const events = load(run)
  const list = calls(events)
  const tests = list.filter((c) => c.name === 'pwsh' && /node (--test|tests)/.test(c.cmd))
  const firstTest = list.findIndex((c) => c.name === 'pwsh' && /node (--test|tests)/.test(c.cmd))
  const written = new Set()
  let verifyReReads = 0
  for (const c of list) {
    if (c.name === 'write' || c.name === 'edit') written.add(c.path)
    else if (c.name === 'read' && written.has(c.path)) verifyReReads += 1
  }
  const writes = list.filter((c) => c.name === 'write' || c.name === 'edit').length
  const after = firstTest < 0 ? list.length : list.length - firstTest
  const compactions = events.filter((e) => e.type === 'compaction/start').length
  console.log(
    `${run} calls=${list.length} compact=${compactions} tests=${tests.length} firstTest@${firstTest} ` +
    `writes=${writes} distinctWritten=${written.size} verifyReReads=${verifyReReads} callsAfterFirstTest=${after}`,
  )
}
