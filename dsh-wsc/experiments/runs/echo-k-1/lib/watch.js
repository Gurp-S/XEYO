import { readdir, stat } from 'node:fs/promises';
import path from 'node:path';

// A watcher that only needs the source tree to be readable: a poll of
// (path, size, mtime) keeps working on network shares and in editors that save
// through rename, where fs.watch() silently stops delivering events.
export async function snapshot(root) {
  const seen = new Map();
  async function walk(abs, rel) {
    let entries;
    try {
      entries = await readdir(abs, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const nextRel = rel ? `${rel}/${entry.name}` : entry.name;
      const nextAbs = path.join(abs, entry.name);
      if (entry.isDirectory()) {
        await walk(nextAbs, nextRel);
      } else if (entry.isFile()) {
        try {
          const info = await stat(nextAbs);
          seen.set(nextRel, `${info.size}:${info.mtimeMs}`);
        } catch {
          // The file vanished between readdir and stat; the next poll sees it.
        }
      }
    }
  }
  await walk(root, '');
  return seen;
}

export function sameSnapshot(left, right) {
  if (left.size !== right.size) return false;
  for (const [key, value] of left) {
    if (right.get(key) !== value) return false;
  }
  return true;
}

export async function watch({ root, intervalMs = 100, onChange, onError = () => {} }) {
  let current = await snapshot(root);
  let stopped = false;
  let timer = null;

  const tick = async () => {
    if (stopped) return;
    try {
      const next = await snapshot(root);
      if (!sameSnapshot(current, next)) {
        current = next;
        await onChange();
      }
    } catch (error) {
      onError(error);
    }
    if (!stopped) timer = setTimeout(tick, intervalMs);
  };

  timer = setTimeout(tick, intervalMs);
  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
  };
}
