import { watch as fsWatch } from 'node:fs';
import { readdir } from 'node:fs/promises';
import path from 'node:path';

const DEFAULT_DEBOUNCE = 80;

// Every directory the source tree currently contains. `fs.watch` is attached
// per directory rather than with `recursive: true`, which is not portable.
async function directories(root) {
  const found = [root];
  let entries;
  try {
    entries = await readdir(root, { withFileTypes: true });
  } catch {
    return found;
  }
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    found.push(...(await directories(path.join(root, entry.name))));
  }
  return found;
}

// Watches a source tree and calls `onChange` once per burst of filesystem
// events. Directory watchers are re-synced on every burst so directories
// created later are picked up. Returns a handle whose `close()` stops it.
export function watchTree(root, onChange, { debounceMs = DEFAULT_DEBOUNCE } = {}) {
  const watchers = new Map();
  let timer = null;
  let closed = false;

  const schedule = () => {
    if (closed) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      sync().then(() => {
        if (!closed) onChange();
      }, () => {
        if (!closed) onChange();
      });
    }, debounceMs);
  };

  const sync = async () => {
    const dirs = new Set(await directories(root));
    for (const [dir, watcher] of watchers) {
      if (dirs.has(dir)) continue;
      watcher.close();
      watchers.delete(dir);
    }
    for (const dir of dirs) {
      if (watchers.has(dir)) continue;
      try {
        const watcher = fsWatch(dir, schedule);
        watcher.on('error', () => {});
        watchers.set(dir, watcher);
      } catch {
        // A directory can vanish between listing it and watching it.
      }
    }
  };

  sync();

  return {
    close() {
      if (closed) return;
      closed = true;
      if (timer) clearTimeout(timer);
      timer = null;
      for (const watcher of watchers.values()) watcher.close();
      watchers.clear();
    },
  };
}
