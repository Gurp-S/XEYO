import { watch } from 'node:fs';
import path from 'node:path';
import { build } from './build.js';

const DEBOUNCE_MS = 75;
const RETRY_MS = 250;
const POLL_MS = 300;

/** One-line human summary shared by the one-shot and watch modes. */
export function formatReport(report) {
  return `built ${report.built.length}, skipped ${report.skipped.length}, removed ${report.removed.length} in ${report.durationMs}ms`;
}

function canWatch(dir) {
  try {
    const probe = watch(dir, { recursive: false }, () => {});
    probe.close();
    return true;
  } catch {
    return false;
  }
}

/**
 * Rebuild whenever the source tree changes.
 *
 * The loop never decides what to rebuild: it only re-runs the normal
 * incremental build, whose content fingerprints make an idle pass a no-op.
 * That keeps watch mode from drifting away from the one-shot contract.
 */
export async function watchBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const oneShot = { ...opts, watch: false };
  const closers = [];
  let running = false;
  let queued = false;
  let timer = null;
  let retry = null;
  let stopped = false;

  const run = async () => {
    if (stopped) return;
    if (running) {
      queued = true;
      return;
    }
    running = true;
    try {
      const report = await build(oneShot, cwd);
      process.stdout.write(opts.json ? `${JSON.stringify(report)}\n` : `${formatReport(report)}\n`);
    } catch (error) {
      process.stderr.write(`build failed: ${error instanceof Error ? error.message : String(error)}\n`);
    } finally {
      running = false;
      if (queued && !stopped) {
        queued = false;
        await run();
      }
    }
  };

  const schedule = () => {
    if (stopped) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      run();
    }, DEBOUNCE_MS);
  };

  process.stdout.write(`watching ${opts.src} for changes\n`);
  await run();

  const attach = () => {
    try {
      const watcher = watch(srcDir, { recursive: true }, schedule);
      watcher.on('error', () => {});
      closers.push(() => watcher.close());
      return true;
    } catch {
      return false;
    }
  };

  if (attach()) {
    schedule();
  } else if (canWatch(srcDir)) {
    // Recursive watching is unavailable on this platform: poll instead. Each
    // poll is an incremental build, so unchanged sources cost almost nothing.
    const poll = setInterval(schedule, POLL_MS);
    closers.push(() => clearInterval(poll));
    schedule();
  } else {
    // The source root does not exist yet; keep trying until it appears.
    retry = setInterval(() => {
      if (!attach()) return;
      clearInterval(retry);
      retry = null;
      schedule();
    }, RETRY_MS);
    closers.push(() => clearInterval(retry));
  }

  return new Promise((resolve) => {
    const stop = () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      if (retry) clearInterval(retry);
      for (const close of closers) {
        try {
          close();
        } catch {
          // A watcher that is already closed is not an error worth reporting.
        }
      }
      resolve();
    };
    process.once('SIGINT', stop);
    process.once('SIGTERM', stop);
  });
}
