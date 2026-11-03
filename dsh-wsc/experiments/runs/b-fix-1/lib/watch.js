import { watch } from 'node:fs';
import { readdir } from 'node:fs/promises';
import path from 'node:path';

export const WATCH_DEBOUNCE_MS = 60;

function isInside(parent, child) {
  const base = parent.endsWith(path.sep) ? parent : `${parent}${path.sep}`;
  return child === parent || child.startsWith(base);
}

// Build output, the manifest and our own temp files must never trigger a rebuild.
export function shouldIgnore(abs, { outDir, manifestPath }) {
  if (abs === manifestPath) return true;
  if (isInside(outDir, abs)) return true;
  const base = path.basename(abs);
  return base.startsWith('.') && base.endsWith('.tmp');
}

// One non-recursive watcher per directory: portable across platforms and it
// keeps working when directories are created or removed while watching.
export async function watchTree(root, onChange) {
  const watchers = new Map();
  let closed = false;

  const add = (dir) => {
    if (closed || watchers.has(dir)) return;
    try {
      const watcher = watch(dir, { persistent: true }, (event, name) => {
        onChange(name ? path.join(dir, name) : dir, event);
      });
      watcher.on('error', () => {});
      watchers.set(dir, watcher);
    } catch {
      // Directory vanished between readdir and watch: nothing to watch.
    }
  };

  const refresh = async () => {
    const seen = new Set();
    const stack = [root];
    while (stack.length > 0) {
      const dir = stack.pop();
      if (seen.has(dir)) continue;
      seen.add(dir);
      add(dir);
      let entries;
      try {
        entries = await readdir(dir, { withFileTypes: true });
      } catch {
        continue;
      }
      for (const entry of entries) {
        if (entry.isDirectory()) stack.push(path.join(dir, entry.name));
      }
    }
    for (const [dir, watcher] of [...watchers]) {
      if (seen.has(dir)) continue;
      try {
        watcher.close();
      } catch {
        // Already closed.
      }
      watchers.delete(dir);
    }
  };

  await refresh();

  return {
    refresh,
    async close() {
      closed = true;
      for (const watcher of watchers.values()) {
        try {
          watcher.close();
        } catch {
          // Already closed.
        }
      }
      watchers.clear();
    },
  };
}

// Rebuild on every change; a failing build is reported and watching continues.
export async function runWatch(opts, { build, cwd = process.cwd(), onReport, onError, debounceMs = WATCH_DEBOUNCE_MS } = {}) {
  if (typeof build !== 'function') throw new Error('runWatch needs a build function');
  const srcDir = path.resolve(cwd, opts.src);
  const ignore = {
    outDir: path.resolve(cwd, opts.out),
    manifestPath: path.resolve(cwd, opts.manifest),
  };

  let timer = null;
  let closed = false;
  let running = false;
  let queued = false;
  let resolveDone;
  const done = new Promise((resolve) => {
    resolveDone = resolve;
  });

  const tree = await watchTree(srcDir, (abs) => {
    if (shouldIgnore(path.resolve(abs), ignore)) return;
    schedule();
  });

  function schedule(delay = debounceMs) {
    if (closed) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      if (running) {
        queued = true;
        return;
      }
      runOnce();
    }, delay);
  }

  async function runOnce() {
    if (closed) return;
    running = true;
    try {
      const report = await build(opts, cwd);
      if (!closed) onReport?.(report);
    } catch (error) {
      if (!closed) onError?.(error);
    } finally {
      running = false;
      await tree.refresh();
      if (queued && !closed) {
        queued = false;
        schedule(0);
      }
    }
  }

  const close = () => {
    if (closed) return;
    closed = true;
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    tree.close().then(resolveDone, resolveDone);
  };

  await runOnce();
  return { done, close, refresh: tree.refresh };
}
