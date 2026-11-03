#!/usr/bin/env node
/**
 * Assert that each experiment arm runs the source that is on disk.
 *
 * Every arm profile carries its own copy of the plugin under
 * `node_modules/@xeyo/dsh-wsc`. A copy that predates a source edit silently
 * runs the old behaviour, which is indistinguishable from "the flag does
 * nothing" in the results. This check compares the repository files with the
 * installed copies by content hash and exits non-zero on any mismatch, so a
 * stale copy fails the run instead of wasting it.
 *
 * Usage: node tools/verify-arms.mjs [armName...]
 */
import { createHash } from 'node:crypto'
import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const repo = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const profiles = join(homedir(), '.dsh', 'profiles')

/** Files that make up the plugin's runtime behaviour. */
function runtimeFiles(root) {
  const libDir = join(root, 'lib')
  const libs = existsSync(libDir)
    ? readdirSync(libDir).filter((name) => name.endsWith('.js')).map((name) => join('lib', name))
    : []
  // `package.json` carries the version and test script, not behaviour: a copy
  // made before a version bump is still the same code.
  return ['index.js', 'engine.js', ...libs]
}

const hash = (path) => createHash('sha256').update(readFileSync(path)).digest('hex')

const wanted = process.argv.slice(2)
const arms = readdirSync(profiles)
  .filter((name) => name.startsWith('ab-'))
  .filter((name) => wanted.length === 0 || wanted.includes(name))
  .sort()

if (arms.length === 0) {
  console.log('no arm profiles found')
  process.exit(1)
}

let failures = 0
for (const arm of arms) {
  const pkg = join(profiles, arm, 'node_modules', '@xeyo', 'dsh-wsc')
  if (!existsSync(pkg)) {
    // Profiles from earlier experiments keep no copy; they are not runnable
    // arms, so they are reported and skipped rather than failed.
    console.log(`${arm}: skipped (no package copy)`)
    continue
  }
  const stale = []
  for (const rel of runtimeFiles(repo)) {
    const source = join(repo, rel)
    const copy = join(pkg, rel)
    if (!existsSync(copy)) stale.push(`${rel} (absent)`)
    else if (hash(source) !== hash(copy)) stale.push(rel)
  }
  if (stale.length === 0) console.log(`${arm}: matches source`)
  else {
    console.log(`${arm}: STALE -> ${stale.join(', ')}`)
    failures += 1
  }
}

process.exit(failures === 0 ? 0 : 1)
