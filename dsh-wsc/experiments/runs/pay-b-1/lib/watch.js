import path from 'node:path';
import { cacheKey } from './cache.js';
import { mapPool } from './pool.js';
import { walk } from './walk.js';

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Map of source-relative path -> content fingerprint for the whole tree. */
export async function snapshot(srcDir, limit, skip = null) {
  const files = await walk(srcDir, srcDir, skip);
  const entries = await mapPool(files, limit, async (rel) => [rel, await cacheKey(path.join(srcDir, rel))]);
  return new Map(entries);
}

export function sameSnapshot(a, b) {
  if (a.size !== b.size) return false;
  for (const [rel, key] of a) if (b.get(rel) !== key) return false;
  return true;
}

/**
 * Poll the source tree and run `onChange` whenever its contents differ from
 * the previous cycle. Polling (rather than fs.watch) keeps the watcher
 * portable and makes "changed" mean "the bytes changed", so a touch without an
 * edit causes no rebuild and an edit that preserves mtime is still seen.
 * Resolves when `signal` aborts.
 */
export async function watchSources({ srcDir, outDir, concurrency, intervalMs = 150, signal, onChange, onError }) {
  const skip = outDir ? (abs) => abs === outDir : null;
  let current = await snapshot(srcDir, concurrency, skip);
  while (!signal?.aborted) {
    await sleep(intervalMs);
    if (signal?.aborted) break;
    let next;
    try {
      next = await snapshot(srcDir, concurrency, skip);
    } catch (error) {
      onError?.(error);
      continue;
    }
    if (sameSnapshot(current, next)) continue;
    for (let settle = 0; settle < 20; settle += 1) {
      await sleep(intervalMs);
      const again = await snapshot(srcDir, concurrency, skip).catch(() => next);
      if (sameSnapshot(next, again)) break;
      next = again;
    }
    current = next;
    try {
      await onChange();
    } catch (error) {
      onError?.(error);
    }
  }
}
