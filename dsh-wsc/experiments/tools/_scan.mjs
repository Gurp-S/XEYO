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
for (const name of ["a-1", "a-2", "a-3", "b-1", "b-2", "b-3"]) {
  const sums = pick(name).filter((e) => e.type === "compaction/summary")
  let watch = 0, conc = 0, len = 0, userTrunc = 0
  for (const s of sums) {
    const d = s.data ?? {}
    const text = typeof d.summary === "string" ? d.summary : JSON.stringify(d.summary ?? d)
    len += text.length
    if (text.includes("--watch")) watch += 1
    if (text.includes("--concurrency")) conc += 1
    if (text.includes("half-written manifest that crashes the ne\n") || /crashes the ne(?!xt)/.test(text)) userTrunc += 1
  }
  console.log(`${name}: summaries=${sums.length} avgChars=${Math.round(len / Math.max(1, sums.length))} withWatch=${watch} withConcurrency=${conc} userBlockTruncated=${userTrunc}`)
}

