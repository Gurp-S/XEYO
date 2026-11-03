import { watch } from 'node:fs';
import path from 'node:path';
import { build, listDirs } from './build.js';

const DEBOUNCE_MS = 50;

/**
 * Watch the source tree and rebuild on change.
 *
 * One non-recursive `fs.watch` per directory: recursive watching is not
 * portable (and unsupported on Linux), so the watcher set is re-synced after
 * every build to pick up directories that appeared or disappeared.
 *
 * Builds are serialised. Events that arrive while a build is running are
 * coalesced into exactly one follow-up build, so a burst of writes never
 * queues more work than the tree can settle.
 */
export async function watchBuild(opts, cwd = process.cwd(), handlers = {}) {
  const { onReport = () => {}, onError = () => {} } = handlers;
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const watchers = new Map();
  let timer = null;
  let running = false;
  let pending = false;
  let closed = false;
  let current = null;

  const ignored = (abs) => {
    const resolved = path.resolve(abs);
    return (
      resolved === manifestPath ||
      resolved === outDir ||
      resolved.startsWith(outDir + path.sep)
    );
  };

  const closeAll = () => {
    for (const watcher of watchers.values()) watcher.close();
    watchers.clear();
  };

  async function sync() {
    const dirs = await listDirs(srcDir);
    const wanted = new Set(dirs);
    for (const [dir, watcher] of watchers) {
      if (!wanted.has(dir)) {
        watcher.close();
        watchers.delete(dir);
      }
    }
    for (const dir of dirs) {
      if (watchers.has(dir)) continue;
      let watcher;
      try {
        watcher = watch(dir, (_event, filename) => {
          if (!filename) return schedule();
          if (ignored(path.join(dir, filename.toString()))) return;
          schedule();
        });
      } catch {
        continue; // directory vanished between listing and watching
      }
      watcher.on('error', () => {
        watcher.close();
        watchers.delete(dir);
      });
      watchers.set(dir, watcher);
    }
  }

  function schedule() {
    if (closed) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      run();
    }, DEBOUNCE_MS);
  }

  async function run() {
    if (closed) return;
    if (running) {
      pending = true;
      return;
    }
    running = true;
    try {
      const report = await build(opts, cwd);
      onReport(report);
    } catch (err) {
      onError(err);
    } finally {
      running = false;
      await sync().catch(() => {});
      if (pending && !closed) {
        pending = false;
        schedule();
      }
    }
  }

  await sync();
  current = run();
  await current;

  return {
    async close() {
      closed = true;
      if (timer) clearTimeout(timer);
      timer = null;
      closeAll();
      await current;
    },
  };
}
