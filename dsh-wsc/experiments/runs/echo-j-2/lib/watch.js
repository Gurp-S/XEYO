import { watch as fsWatch, readdirSync } from 'node:fs';
import path from 'node:path';
import { build } from './engine.js';

const IGNORED = /(^|[\\/])(?:\.|~)/;

function watchTree(root, onChange) {
  const closers = [];
  const arm = (dir) => {
    let watcher;
    try {
      watcher = fsWatch(dir, (event, file) => {
        if (file && IGNORED.test(file.toString())) return;
        onChange(event, file);
      });
    } catch {
      return;
    }
    watcher.on('error', () => {});
    closers.push(() => watcher.close());
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.isDirectory() && !IGNORED.test(entry.name)) arm(path.join(dir, entry.name));
    }
  };
  arm(root);
  return () => closers.forEach((close) => close());
}

// Builds once, then rebuilds after every burst of changes. Changes that arrive
// during a build are collapsed into a single follow-up build.
export function startWatch(opts, cwd, report, { debounceMs = 60 } = {}) {
  const srcDir = path.resolve(cwd, opts.src);
  let timer = null;
  let running = false;
  let queued = false;
  let closed = false;

  const run = async () => {
    if (closed) return;
    if (running) {
      queued = true;
      return;
    }
    running = true;
    try {
      report(await build(opts, cwd));
    } catch (error) {
      report({ error: error.message });
    } finally {
      running = false;
      if (queued) {
        queued = false;
        schedule();
      }
    }
  };

  const schedule = () => {
    if (closed) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(run, debounceMs);
  };

  let unwatch;
  try {
    const watcher = fsWatch(srcDir, { recursive: true }, (event, file) => {
      if (file && IGNORED.test(file.toString())) return;
      schedule();
    });
    watcher.on('error', () => {});
    unwatch = () => watcher.close();
  } catch {
    // Platforms without recursive watching fall back to one watcher per directory.
    unwatch = watchTree(srcDir, schedule);
  }

  run();
  return {
    close() {
      closed = true;
      if (timer) clearTimeout(timer);
      unwatch();
    },
  };
}
