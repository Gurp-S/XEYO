import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import zlib from 'node:zlib'

const M = Buffer.from([0x28, 0xb5, 0x2f, 0xfd])
function frames(b) {
  const s = []
  for (let i = 0; i + 4 <= b.length; i++) if (b.compare(M, 0, 4, i, i + 4) === 0) s.push(i)
  const o = []
  for (let k = 0; k < s.length; k++) {
    const e = k + 1 < s.length ? s[k + 1] : b.length
    try { o.push(zlib.zstdDecompressSync(b.subarray(s[k], e)).toString('utf8')) } catch {}
  }
  return o
}
const base = path.join(os.homedir(), '.dsh', 'sessions')
function load(run) {
  const dir = fs.readdirSync(base).find(d => d.includes('runs-' + run + '--'))
  const walk = p => {
    for (const e of fs.readdirSync(p, { withFileTypes: true })) {
      const q = path.join(p, e.name)
      if (e.isDirectory()) { const h = walk(q); if (h) return h } else if (e.name.endsWith('.zstd')) return q
    }
    return null
  }
  return frames(fs.readFileSync(walk(path.join(base, dir)))).join('').split(/\r?\n/)
    .filter(l => l.trim()).map(l => { try { return JSON.parse(l) } catch { return null } }).filter(Boolean)
}

const ledger = fs.readFileSync(path.join(os.homedir(), '.dsh', 'wsc', 'compactions.jsonl'), 'utf8')
  .trim().split(/\r?\n/).map(l => JSON.parse(l))
const med = a => { a = a.slice().sort((x, y) => x - y); return a.length ? a[Math.floor(a.length / 2)] : 0 }
const sum = a => a.reduce((x, y) => x + y, 0)

for (const run of process.argv.slice(2)) {
  const ev = load(run)
  const tools = ev.filter(e => e.type === 'tool/call').map(e => e.data.name)
  const hist = {}
  for (const t of tools) hist[t] = (hist[t] || 0) + 1
  const top = Object.entries(hist).sort((a, b) => b[1] - a[1]).slice(0, 6)
  const reads = ev.filter(e => e.type === 'tool/call' && e.data.name === 'read')
    .map(e => { try { return JSON.parse(e.data.arguments).file_path } catch { return '?' } })
  const dup = reads.length - new Set(reads).size
  const starts = ev.filter(e => e.type === 'compaction/start')
  const ends = ev.filter(e => e.type === 'compaction/end')
  const durs = starts.map(s => { const e = ends.find(x => x.data.compactionId === s.data.compactionId); return e ? (e.time - s.time) / 1000 : 0 })
  const times = ev.map(e => e.time).filter(t => Number.isFinite(t))
  const t0 = Math.min(...times), t1 = Math.max(...times)
  const iso = new Date(t0).toISOString().slice(0, 16), iso2 = new Date(t1).toISOString().slice(0, 16)
  const rows = ledger.filter(r => r.at >= iso + ':00' && r.at <= iso2 + ':59')
  const sh = rows.map(r => r.shadowedTokens || 0), out = rows.map(r => (r.selection && r.selection.outputTokens) || 0)
  const reasons = {}
  for (const r of rows) { const k = (r.selection && (r.selection.reason || r.selection.strategy)) || r.reason || '?' ; reasons[k] = (reasons[k] || 0) + 1 }
  console.log('== ' + run)
  console.log('  steps=' + ev.filter(e => e.type === 'step/start').length + ' tools=' + tools.length +
    ' compactions=' + starts.length + ' span=' + Math.round((t1 - t0) / 1000) + 's')
  console.log('  compaction time total=' + Math.round(sum(durs)) + 's median=' + Math.round(med(durs)) + 's max=' + Math.round(Math.max(0, ...durs)) + 's')
  console.log('  tool mix: ' + top.map(([k, v]) => k + ':' + v).join(' '))
  console.log('  read calls=' + reads.length + ' distinct=' + new Set(reads).size + ' repeats=' + dup)
  console.log('  ledger rows=' + rows.length + ' median region=' + med(sh) + ' median selOut=' + med(out) +
    ' keep=' + (med(sh) ? (med(out) / med(sh)).toFixed(2) : '-'))
  console.log('  reasons: ' + Object.entries(reasons).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([k, v]) => k + ':' + v).join(' '))
}
