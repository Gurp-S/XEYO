import { watch } from 'node:fs';
import { readdir } from 'node:fs/promises';
import path from 'node:path';
import { build } from './build.js';

// Editors write in bursts (write, rename, chmod), so a change only schedules a
// build once the tree has been quiet for a moment.
const DEBOUNCE_MS = 75;

// Every directory under the source root. Directories reached through a symlink
// are not listed, matching `walk` in the builder, so watch mode never sees a
// file the build itself would ignore.
async function listDirs(root) {
  const dirs = [];
  const queue = [root];
  while (queue.length > 0) {
    const dir = queue.shift();
    let entries;
    try {
      entries = await readdir(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    dirs.push(dir);
    for (const entry of entries) {
      if (entry.isDirectory()) queue.push(path.join(dir, entry.name));
    }
  }
  return dirs;
}

// Rebuild whenever anything under `opts.src` changes. Resolves once `signal`
// aborts, after every watcher has been closed; the caller owns the lifetime.
//
// `onChange(report)` runs after each successful build and `onChange(null,
// error)` after a failed one, so a broken build reports itself and the watcher
// keeps running for the fix.
export async function watchBuild(opts, { cwd = process.cwd(), signal, onChange = () => {} } = {}) {
  const srcDir = path.resolve(cwd, opts.src);
  const parentDir = path.dirname(srcDir);
  const watchers = new Map();
  let timer = null;
  let running = false;
  let pending = false;
  let finish = null;
  let stopped = false;

  const schedule = () => {
    if (stopped) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      void refresh();
    }, DEBOUNCE_MS);
  };

  const addWatcher = (dir) => {
    if (watchers.has(dir)) return;
    try {
      const watcher = watch(dir, () => schedule());
      watcher.on('error', () => {
        watcher.close();
        watchers.delete(dir);
        schedule();
      });
      watchers.set(dir, watcher);
    } catch {
      // The directory vanished between listing and watching; the change that
      // removed it already scheduled a rescan.
    }
  };

  // Keep one watcher per existing directory. New directories appear in the
  // rescan that the change creating them already triggered.
  const sync = async () => {
    const dirs = await listDirs(srcDir);
    const wanted = new Set(dirs);
    for (const [dir, watcher] of watchers) {
      if (!wanted.has(dir)) {
        watcher.close();
        watchers.delete(dir);
      }
    }
    if (dirs.length === 0) {
      // A missing source root is watched through its parent so that creating
      // it brings the watcher back instead of ending the session.
      addWatcher(parentDir);
      return;
    }
    for (const dir of dirs) addWatcher(dir);
    if (watchers.has(parentDir) && !wanted.has(parentDir)) {
      watchers.get(parentDir).close();
      watchers.delete(parentDir);
    }
  };

  const run = async () => {
    if (stopped) return;
    if (running) {
      pending = true;
      return;
    }
    running = true;
    try {
      const report = await build(opts, cwd);
      onChange(report);
    } catch (error) {
      onChange(null, error);
    } finally {
      running = false;
      if (pending) {
        pending = false;
        schedule();
      }
    }
  };

  const refresh = async () => {
    await sync();
    await run();
  };

  const stop = () => {
    if (stopped) return;
    stopped = true;
    if (timer) clearTimeout(timer);
    timer = null;
    for (const watcher of watchers.values()) watcher.close();
    watchers.clear();
    if (finish) finish();
  };

  if (signal) {
    if (signal.aborted) {
      stop();
      return;
    }
    signal.addEventListener('abort', stop, { once: true });
  }

  const closed = new Promise((resolve) => {
    finish = resolve;
  });

  await refresh();
  await closed;
}
