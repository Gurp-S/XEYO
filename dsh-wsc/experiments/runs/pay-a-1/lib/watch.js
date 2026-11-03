import { watch as fsWatch } from 'node:fs';
import path from 'node:path';
import { build } from './build.js';
import { createOwned } from './owned.js';

export const DEFAULT_DEBOUNCE_MS = 50;

/**
 * Rebuild on every source change until `close()` is called.
 *
 * The watcher is attached *before* the first build, so a change that lands while
 * that build is running is still observed. Builds never overlap: a change that
 * arrives mid-build queues exactly one follow-up run, and bursts of events
 * collapse into one build through the debounce timer.
 *
 * Anything the build itself writes (`out/`, the manifest) is ignored, so a
 * configuration where `--out` lives under `--src` cannot feed back on itself.
 */
export function startWatch(
  opts,
  { cwd = process.cwd(), onReport = () => {}, onError = () => {}, debounceMs = DEFAULT_DEBOUNCE_MS } = {},
) {
  const srcDir = path.resolve(cwd, opts.src);
  const { isOwned } = createOwned({ cwd, opts });

  let closed = false;
  let running = false;
  let pending = false;
  let timer = null;

  const selfInflicted = isOwned;

  const run = async () => {
    if (closed || running) {
      if (running) pending = true;
      return;
    }
    running = true;
    try {
      onReport(await build(opts, cwd));
    } catch (error) {
      onError(error);
    } finally {
      running = false;
      if (pending) {
        pending = false;
        schedule();
      }
    }
  };

  function schedule() {
    if (closed) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      void run();
    }, debounceMs);
  }

  const watcher = fsWatch(srcDir, { recursive: true }, (_event, filename) => {
    if (filename && selfInflicted(path.resolve(srcDir, filename.toString()))) return;
    schedule();
  });
  watcher.on('error', onError);

  void run();

  return {
    close() {
      if (closed) return;
      closed = true;
      if (timer) clearTimeout(timer);
      timer = null;
      watcher.close();
    },
  };
}
