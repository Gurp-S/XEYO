import { watch as fsWatch } from 'node:fs';
import path from 'node:path';
import { build, formatReport } from './build.js';

// Changes usually arrive in bursts (an editor writing a file, a formatter rewriting
// several), so a rebuild starts only after the tree has been quiet for a moment.
export const DEBOUNCE_MS = 50;

function messageOf(error) {
  return error instanceof Error ? error.message : String(error);
}

// fs.watch reports paths relative to the watched directory. A build writes its outputs
// and manifest below the source tree when the caller points --out there, and those
// writes must not trigger another build.
function isOwnOutput(filename, opts, cwd, srcDir) {
  if (!filename) return false;
  const abs = path.resolve(srcDir, filename);
  const outDir = path.resolve(cwd, opts.out);
  const manifest = path.resolve(cwd, opts.manifest);
  return abs === manifest || abs === outDir || abs.startsWith(outDir + path.sep);
}

// Builds once, then rebuilds whenever a source file changes. Builds never overlap: a
// change that lands mid-build is coalesced into one follow-up build, so the outputs on
// disk always come from the newest source state.
export async function watchBuild(opts, io = {}) {
  const cwd = io.cwd ?? process.cwd();
  const out = io.out ?? ((line) => process.stdout.write(line));
  const err = io.err ?? ((line) => process.stderr.write(line));
  const srcDir = path.resolve(cwd, opts.src);

  let closed = false;
  let running = false;
  let pending = false;
  let timer = null;
  let settle;
  const done = new Promise((resolve) => {
    settle = resolve;
  });

  const runBuild = async () => {
    if (closed) return;
    if (running) {
      pending = true;
      return;
    }
    running = true;
    try {
      const report = await build(opts, cwd);
      out(formatReport(report, opts.json));
    } catch (error) {
      err(`build failed: ${messageOf(error)}\n`);
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
      runBuild();
    }, DEBOUNCE_MS);
  }

  const watcher = fsWatch(srcDir, { recursive: true });
  watcher.on('change', (_event, filename) => {
    if (!isOwnOutput(filename, opts, cwd, srcDir)) schedule();
  });
  watcher.on('error', (error) => err(`watch failed: ${messageOf(error)}\n`));

  const stop = () => {
    if (closed) return;
    closed = true;
    if (timer) clearTimeout(timer);
    timer = null;
    watcher.close();
    settle(0);
  };
  process.once('SIGINT', stop);
  process.once('SIGTERM', stop);

  await runBuild();
  return done;
}
