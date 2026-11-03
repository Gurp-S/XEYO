import { watch as watchFs } from 'node:fs';
import { readdir, stat } from 'node:fs/promises';
import path from 'node:path';
import { build } from './build.js';

// A source-tree snapshot is only used to decide whether something changed; the
// build itself re-reads every file, so a coarse fingerprint is enough.
async function snapshot(dir, base = dir, out = new Map()) {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      await snapshot(abs, base, out);
    } else if (entry.isFile()) {
      try {
        const info = await stat(abs);
        out.set(path.relative(base, abs), `${info.size}:${info.mtimeMs}`);
      } catch {
        // A file that vanished between readdir and stat simply does not exist.
      }
    }
  }
  return out;
}

function differs(a, b) {
  if (a.size !== b.size) return true;
  for (const [key, value] of a) if (b.get(key) !== value) return true;
  return false;
}

// Runs one build, reports it, then rebuilds whenever the source tree changes.
// Resolves only when the watcher is closed (SIGINT/SIGTERM).
export async function runWatch(opts, cwd, { emit, notice }) {
  const srcDir = path.resolve(cwd, opts.src);
  const state = { running: false, queued: false, closed: false };
  let current = await snapshot(srcDir);

  const runOnce = async () => {
    if (state.closed) return;
    if (state.running) {
      state.queued = true;
      return;
    }
    state.running = true;
    try {
      const report = await build(opts, cwd);
      current = await snapshot(srcDir);
      await emit(report);
    } catch (error) {
      await emit({ error });
    } finally {
      state.running = false;
      if (state.queued) {
        state.queued = false;
        await runOnce();
      }
    }
  };

  await runOnce();
  await notice();

  let timer = null;
  const schedule = () => {
    if (state.closed) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      void runOnce();
    }, 60);
    timer.unref?.();
  };

  const close = () => {
    if (state.closed) return;
    state.closed = true;
    if (timer) clearTimeout(timer);
    if (watcher) watcher.close();
    clearInterval(poll);
    resolveDone();
  };

  let resolveDone;
  const done = new Promise((resolve) => {
    resolveDone = resolve;
  });

  let watcher = null;
  try {
    // Recursive watching is available on every supported platform; if the
    // platform refuses it, the poll below is the fallback that still works.
    watcher = watchFs(srcDir, { recursive: true }, () => schedule());
    watcher.on('error', () => {
      try {
        watcher.close();
      } catch {
        // Already closed.
      }
      watcher = null;
    });
  } catch {
    watcher = null;
  }

  // Safety net: catches changes the platform watcher misses or coalesces.
  const poll = setInterval(async () => {
    if (state.closed || state.running) return;
    const next = await snapshot(srcDir);
    if (differs(current, next)) {
      current = next;
      await runOnce();
    }
  }, 250);
  poll.unref?.();

  for (const signal of ['SIGINT', 'SIGTERM']) {
    process.once(signal, () => close());
  }

  return done;
}
