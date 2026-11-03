import path from 'node:path';
import { snapshot } from './tree.js';

export const DEFAULT_WATCH_INTERVAL = 200;

function sameSnapshot(a, b) {
  if (a.size !== b.size) return false;
  for (const [rel, key] of a) if (b.get(rel) !== key) return false;
  return true;
}

function delay(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

// Rebuilds whenever the content of the source tree changes. Polling a content
// snapshot (rather than fs.watch events) keeps the watch honest: it sees
// additions, deletions and mtime-preserving rewrites alike, on every platform,
// and needs no dependency.
export async function watchBuild(opts, options = {}) {
  const {
    cwd = process.cwd(),
    intervalMs = DEFAULT_WATCH_INTERVAL,
    build,
    onReport,
    onError,
    signal,
  } = options;
  const srcDir = path.resolve(cwd, opts.src);

  const run = async () => {
    try {
      onReport?.(await build(opts, cwd));
    } catch (error) {
      onError?.(error);
    }
  };

  await run();
  let baseline = await snapshot(srcDir);
  let lastError = null;

  while (!signal?.aborted) {
    await delay(intervalMs);
    if (signal?.aborted) break;
    let current;
    try {
      current = await snapshot(srcDir);
      lastError = null;
    } catch (error) {
      // A file can vanish between readdir and readFile while the tree is being
      // edited; the next poll picks up the settled state.
      if (lastError !== error.message) onError?.(error);
      lastError = error.message;
      continue;
    }
    if (sameSnapshot(baseline, current)) continue;
    baseline = current;
    await run();
    baseline = await snapshot(srcDir);
  }
}
