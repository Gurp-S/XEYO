import { watch } from 'node:fs';
import path from 'node:path';
import { build, formatReport } from './build.js';

const DEBOUNCE_MS = 60;

function describe(error) {
  return error instanceof Error ? error.message : String(error);
}

// Rebuild on every source change until SIGINT/SIGTERM. Only the source tree is
// watched, so writing outputs never feeds back into the loop.
export async function watchBuild(opts, cwd = process.cwd(), io = process) {
  const srcDir = path.resolve(cwd, opts.src);
  let timer = null;
  let running = false;
  let queued = false;
  let closed = false;
  let finish;
  const done = new Promise((resolve) => {
    finish = resolve;
  });

  const run = async () => {
    if (running) {
      queued = true;
      return;
    }
    running = true;
    try {
      io.stdout.write(formatReport(await build(opts, cwd), opts));
    } catch (error) {
      io.stderr.write(`build failed: ${describe(error)}\n`);
    } finally {
      running = false;
      if (queued && !closed) {
        queued = false;
        await run();
      }
    }
  };

  const schedule = () => {
    if (closed) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      void run();
    }, DEBOUNCE_MS);
  };

  const watcher = watch(srcDir, { recursive: true }, schedule);
  watcher.on('error', (error) => io.stderr.write(`watch failed: ${describe(error)}\n`));

  const stop = () => {
    if (closed) return;
    closed = true;
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    watcher.close();
    finish(0);
  };
  const signals = ['SIGINT', 'SIGTERM'];
  for (const signal of signals) process.once(signal, stop);

  try {
    await run();
    return await done;
  } finally {
    for (const signal of signals) process.removeListener(signal, stop);
    watcher.close();
  }
}
