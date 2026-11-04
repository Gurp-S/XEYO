import { readSessionEvents } from "./read-session.mjs"
import { readdirSync, statSync } from "node:fs"
import path from "node:path"
const base = "C:/Users/48522/.dsh/sessions"
const walk = (d) => readdirSync(d).flatMap((n) => { const p = path.join(d, n); return statSync(p).isDirectory() ? walk(p) : [p] })
for (const name of readdirSync(base)) {
  if (!/runs-mega-/.test(name)) continue
  const f = walk(path.join(base, name)).find((x) => x.endsWith(".jsonl.zstd"))
  if (!f) continue
  const ev = readSessionEvents(f)
  console.log(name.replace(/^.*runs-/, "").replace(/--$/, ""), "steps=" + ev.filter((e) => e.type === "step/end").length, "cmp=" + ev.filter((e) => e.type === "compaction/summary").length)
}
