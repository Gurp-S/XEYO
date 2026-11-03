import { watch as watchDirectory } from 'node:fs';
import { readdir } from 'node:fs/promises';
import path from 'node:path';

const DEBOUNCE_MS = 60;

// fs.watch recursive is not available on every platform, so each real
// directory gets its own non-recursive watcher. Symlinked directories are not
// followed, matching how the builder walks sources.
async function listDirectories(root, ignore) {
  const dirs = [];

  async function walk(dir) {
    dirs.push(dir);
    let entries;
    try {
      entries = await readdir(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      const abs = path.join(dir, entry.name);
      if (ignore && (abs === ignore || abs.startsWith(ignore + path.sep))) continue;
      await walk(abs);
    }
  }

  await walk(root);
  return dirs;
}

export async function watchSources(srcDir, onChange, { ignore } = {}) {
  const watchers = new Map();
  let timer = null;
  let busy = false;
  let queued = false;
  let closed = false;

  const ignored = (abs) => Boolean(ignore) && (abs === ignore || abs.startsWith(ignore + path.sep));

  async function syncWatchers() {
    const dirs = await listDirectories(srcDir, ignore);
    const live = new Set(dirs);
    for (const [dir, watcher] of watchers) {
      if (live.has(dir)) continue;
      watcher.close();
      watchers.delete(dir);
    }
    for (const dir of dirs) {
      if (watchers.has(dir)) continue;
      let watcher;
      try {
        watcher = watchDirectory(dir, (event, filename) => {
          if (filename && ignored(path.resolve(dir, String(filename)))) return;
          schedule();
        });
      } catch {
        continue;
      }
      watcher.on('error', () => {
        watcher.close();
        watchers.delete(dir);
        schedule();
      });
      watchers.set(dir, watcher);
    }
  }

  async function rebuild() {
    if (closed) return;
    if (busy) {
      queued = true;
      return;
    }
    busy = true;
    try {
      await syncWatchers();
      if (!closed) await onChange();
    } finally {
      busy = false;
      if (queued) {
        queued = false;
        rebuild();
      }
    }
  }

  function schedule() {
    if (closed) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      rebuild();
    }, DEBOUNCE_MS);
  }

  await syncWatchers();

  return function stop() {
    closed = true;
    if (timer) clearTimeout(timer);
    timer = null;
    for (const watcher of watchers.values()) watcher.close();
    watchers.clear();
  };
}
