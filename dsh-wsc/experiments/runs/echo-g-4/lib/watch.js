import { watch } from 'node:fs';
import path from 'node:path';
import { build } from './build.js';

const DEBOUNCE_MS = 40;

/**
 * Rebuild whenever anything under `src` changes. Watcher events are coalesced
 * so one save that emits several events (write + rename) produces one build.
 * Returns a function that stops watching.
 */
export function watchBuild(opts, { onReport, onError, cwd = process.cwd() } = {}) {
  const srcDir = path.resolve(cwd, opts.src);
  let timer = null;
  let running = false;
  let pending = false;

  const run = async () => {
    if (running) {
      pending = true;
      return;
    }
    running = true;
    try {
      onReport?.(await build(opts, cwd));
    } catch (error) {
      onError?.(error);
    } finally {
      running = false;
      if (pending) {
        pending = false;
        run();
      }
    }
  };

  const watcher = watch(srcDir, { recursive: true }, () => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(run, DEBOUNCE_MS);
  });

  return () => {
    if (timer) clearTimeout(timer);
    watcher.close();
  };
}
