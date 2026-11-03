import { watch as watchDir } from 'node:fs';
import path from 'node:path';
import { build } from './build.js';
import { walkDirs } from './walk.js';

const DEBOUNCE_MS = 50;

// Watch every source directory and rebuild once the tree settles. The caller
// gets one report per completed build; a failed build is reported but keeps
// the watcher alive so the next edit can recover.
export async function startWatch(opts, hooks = {}, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const manifestDir = path.dirname(manifestPath);
  const manifestTempPrefix = `.${path.basename(manifestPath)}.`;
  const { onReport = () => {}, onError = () => {} } = hooks;
  const watchers = new Map();
  let closed = false;
  let timer = null;
  let running = false;
  let pending = false;

  // Writes made by the build itself must never trigger another build.
  function isIgnored(abs) {
    if (abs === outDir || abs.startsWith(`${outDir}${path.sep}`)) return true;
    if (abs === manifestPath) return true;
    return path.dirname(abs) === manifestDir && path.basename(abs).startsWith(manifestTempPrefix);
  }

  async function syncWatchers() {
    const dirs = new Set(await walkDirs(srcDir));
    for (const [dir, watcher] of watchers) {
      if (dirs.has(dir)) continue;
      watcher.close();
      watchers.delete(dir);
    }
    for (const dir of dirs) {
      if (watchers.has(dir)) continue;
      let watcher;
      try {
        watcher = watchDir(dir, (event, filename) => {
          if (closed) return;
          if (filename && isIgnored(path.resolve(dir, filename.toString()))) return;
          schedule();
        });
      } catch (error) {
        if (error.code !== 'ENOENT') onError(error);
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

  function schedule() {
    if (closed) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      void runOnce();
    }, DEBOUNCE_MS);
  }

  async function resync() {
    try {
      await syncWatchers();
    } catch (error) {
      onError(error);
    }
  }

  async function runOnce() {
    if (closed) return;
    if (running) {
      pending = true;
      return;
    }
    running = true;
    try {
      onReport(await build(opts, cwd));
    } catch (error) {
      onError(error);
    } finally {
      running = false;
    }
    await resync();
    if (pending && !closed) {
      pending = false;
      await runOnce();
    }
  }

  function close() {
    if (closed) return;
    closed = true;
    if (timer) clearTimeout(timer);
    timer = null;
    for (const watcher of watchers.values()) watcher.close();
    watchers.clear();
  }

  await syncWatchers();
  await runOnce();
  return { close };
}
