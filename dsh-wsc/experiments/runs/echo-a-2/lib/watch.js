import { watch } from 'node:fs';
import path from 'node:path';
import { build } from './build.js';

// Editors save in bursts (write, rename, chmod), so a change is only turned
// into a rebuild once the directory has been quiet for a moment.
export const DEBOUNCE_MS = 50;

// Rebuilds the tree whenever something under `--src` changes. Rebuilds are
// serialised: changes that arrive while one is in flight collapse into a
// single follow-up run, and `--dry-run` keeps writing nothing.
export function watchBuild(opts, cwd = process.cwd(), hooks = {}) {
  const { onReport = () => {}, onError = () => {} } = hooks;
  const srcDir = path.resolve(cwd, opts.src);
  const pending = new Set();
  let timer = null;
  let running = false;
  let queued = false;
  let closed = false;

  const flush = async () => {
    timer = null;
    if (closed) return;
    if (running) {
      queued = true;
      return;
    }
    running = true;
    try {
      const changed = [...pending];
      pending.clear();
      onReport(await build(opts, cwd), changed);
    } catch (error) {
      pending.clear();
      onError(error);
    } finally {
      running = false;
      if (queued && !closed) {
        queued = false;
        schedule();
      }
    }
  };

  function schedule() {
    if (closed || timer) return;
    timer = setTimeout(flush, DEBOUNCE_MS);
    timer.unref?.();
  }

  const watcher = watch(srcDir, { recursive: true }, (_event, filename) => {
    if (filename) pending.add(String(filename).split(path.sep).join('/'));
    schedule();
  });
  watcher.on('error', onError);

  return {
    srcDir,
    close() {
      closed = true;
      if (timer) clearTimeout(timer);
      timer = null;
      watcher.close();
    },
  };
}
