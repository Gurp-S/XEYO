import { watch as watchFs } from 'node:fs';
import path from 'node:path';
import { build } from './build.js';

const DEBOUNCE_MS = 100;

// Initial build, then one rebuild per settled burst of source changes. Rebuilds
// are serialised so overlapping bursts never race on the output tree.
export async function startWatch(opts, { cwd = process.cwd(), onReport, onError } = {}) {
  const srcDir = path.resolve(cwd, opts.src);
  let timer = null;
  let queue = Promise.resolve();

  const run = () => {
    queue = queue.then(async () => {
      try {
        const report = await build(opts, cwd);
        onReport?.(report);
        return report;
      } catch (error) {
        onError?.(error);
        return null;
      }
    });
    return queue;
  };

  const watcher = watchFs(srcDir, { recursive: true }, () => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      run();
    }, DEBOUNCE_MS);
  });
  watcher.on('error', (error) => onError?.(error));

  await run();

  return {
    close() {
      if (timer) clearTimeout(timer);
      timer = null;
      watcher.close();
      return queue;
    },
  };
}
