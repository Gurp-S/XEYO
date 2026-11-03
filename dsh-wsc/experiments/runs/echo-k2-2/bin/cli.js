import { groups } from '../src/registry.js'

const out = {}
for (const [name, build] of Object.entries(groups)) out[name] = build()
console.log(JSON.stringify(out))
