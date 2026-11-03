import { watch as fsWatch } from 'node:fs';
import path from 'node:path';
import { build } from './build.js';

const DEBOUNCE_MS = 60;

/**
 * Build once, then rebuild on every source change.
 *
 * Rebuilds are serialized: a change arriving mid-build schedules exactly one
 * follow-up cycle, which then observes the final state of the tree. A failed
 * cycle is reported and the watcher keeps running.
 */
export async function watchSources(opts, { cwd = process.cwd(), onReport, onError } = {}) {
  const srcDir = path.resolve(cwd, opts.src);
  let running = false;
  let queued = false;

  const cycle = async (reason) => {
    if (running) {
      queued = true;
      return;
    }
    running = true;
    try {
      onReport(await build(opts, cwd), reason);
    } catch (error) {
      onError(error);
    } finally {
      running = false;
      if (queued) {
        queued = false;
        await cycle('queued');
      }
    }
  };

  let timer = null;
  let changed = new Set();
  const watcher = fsWatch(srcDir, { recursive: true }, (_event, filename) => {
    if (filename) changed.add(String(filename));
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      const names = [...changed].sort();
      changed = new Set();
      void cycle(names.join(', ') || 'change');
    }, DEBOUNCE_MS);
  });
  watcher.on('error', (error) => onError?.(error));

  await cycle('initial');
  return {
    close() {
      if (timer) clearTimeout(timer);
      watcher.close();
    },
  };
}
