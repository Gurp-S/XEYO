import { watch } from 'node:fs';
import { readdir } from 'node:fs/promises';
import path from 'node:path';

const DEBOUNCE_MS = 40;
const RETRY_MS = 200;

// fs.watch is recursive on only some platforms, so one handle per directory is
// kept instead. Every event re-scans the tree before rebuilding: a new file may
// arrive inside a directory that did not exist when the watcher started, and
// that directory needs a handle of its own before its next event can be seen.
export async function createTreeWatcher(root, onChange) {
  const handles = new Map();
  let closed = false;
  let timer = null;
  let retry = null;
  let running = Promise.resolve();

  const listDirs = async (dir) => {
    const dirs = [dir];
    let entries;
    try {
      entries = await readdir(dir, { withFileTypes: true });
    } catch {
      return dirs;
    }
    for (const entry of entries) {
      if (entry.isDirectory()) dirs.push(...(await listDirs(path.join(dir, entry.name))));
    }
    return dirs;
  };

  const sync = async () => {
    const dirs = new Set(await listDirs(root));
    for (const [dir, handle] of handles) {
      if (dirs.has(dir)) continue;
      handle.close();
      handles.delete(dir);
    }
    for (const dir of dirs) {
      if (handles.has(dir) || closed) continue;
      try {
        const handle = watch(dir, () => schedule());
        handle.on('error', () => {
          handle.close();
          handles.delete(dir);
          schedule();
        });
        handles.set(dir, handle);
      } catch {
        // The directory vanished between the scan and the watch call; the next
        // event or retry picks the tree up again.
      }
    }
  };

  // A source tree that does not exist yet leaves nothing to watch, so a retry
  // timer keeps the process alive until it appears.
  const ensureAlive = () => {
    if (closed || retry || handles.size > 0) return;
    retry = setTimeout(() => {
      retry = null;
      running = running.then(refresh).catch(() => {});
    }, RETRY_MS);
  };

  const refresh = async () => {
    if (closed) return;
    await sync();
    ensureAlive();
    if (closed) return;
    await onChange();
  };

  function schedule() {
    if (closed) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      running = running.then(refresh).catch(() => {});
    }, DEBOUNCE_MS);
  }

  return {
    async start() {
      await sync();
      ensureAlive();
    },
    close() {
      closed = true;
      if (timer) clearTimeout(timer);
      if (retry) clearTimeout(retry);
      timer = null;
      retry = null;
      for (const handle of handles.values()) handle.close();
      handles.clear();
    },
  };
}
