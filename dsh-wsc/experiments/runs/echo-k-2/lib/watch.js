import { watch } from 'node:fs';
import path from 'node:path';
import { build } from './build.js';

const DEBOUNCE_MS = 40;

// Runs one build, then rebuilds whenever anything under `opts.src` changes.
// Builds never overlap: a change that lands mid-build queues exactly one
// follow-up build once the current one settles.
export function watchBuild(opts, handlers = {}) {
  const cwd = handlers.cwd ?? process.cwd();
  const onReport = handlers.onReport ?? (() => {});
  const onError = handlers.onError ?? (() => {});
  const srcDir = path.resolve(cwd, opts.src);

  let closed = false;
  let building = false;
  let queued = false;
  let timer = null;

  const run = async (reason) => {
    if (closed) return;
    if (building) {
      queued = true;
      return;
    }
    building = true;
    try {
      onReport(await build(opts, cwd), reason);
    } catch (error) {
      onError(error, reason);
    } finally {
      building = false;
      if (queued && !closed) {
        queued = false;
        schedule('change during build');
      }
    }
  };

  const schedule = (reason) => {
    if (closed) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      run(reason);
    }, DEBOUNCE_MS);
  };

  const watcher = watch(srcDir, { recursive: true }, (_event, filename) => {
    const name = filename ? String(filename).split(path.sep).join('/') : '';
    schedule(name ? `change: ${name}` : 'change');
  });
  watcher.on('error', (error) => {
    if (!closed) onError(error, 'watch');
  });

  run('initial');

  return {
    close() {
      if (closed) return;
      closed = true;
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      watcher.close();
    },
  };
}
