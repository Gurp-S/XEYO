import { readdirSync } from "node:fs"
import { join } from "node:path"
import { homedir } from "node:os"
import { readSessionEvents } from "./read-session.mjs"
const base = join(homedir(), ".dsh", "sessions")
const pick = (name) => {
  const dir = readdirSync(base).find((e) => e.includes(`runs-${name}--`))
  const files = readdirSync(join(base, dir), { recursive: true }).filter((f) => String(f).endsWith("session.jsonl.zstd"))
  return readSessionEvents(join(base, dir, files[0]))
}
for (const name of ["b-1", "a-1"]) {
  const events = pick(name)
  const sums = events.filter((e) => e.type === "compaction/summary")
  console.log(`\n######## ${name}: ${sums.length} summaries`)
  const s = sums[0]
  const d = s.data ?? {}
  const text = typeof d.summary === "string" ? d.summary : JSON.stringify(d.summary ?? d)
  console.log(`--- keys: ${Object.keys(d).join(",")}`)
  console.log(text.slice(0, 2200))
}

