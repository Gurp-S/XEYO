#!/usr/bin/env node
import path from 'node:path';
import { build, parseArgs, USAGE } from '../lib/build.js';
import { watchTree } from '../lib/watch.js';

function describe(report) {
  return `built ${report.built.length}, skipped ${report.skipped.length}, removed ${report.removed.length} in ${report.durationMs}ms`;
}

function printReport(report, opts) {
  process.stdout.write(opts.json ? `${JSON.stringify(report)}\n` : `${describe(report)}\n`);
}

function failure(error) {
  return `build failed: ${error instanceof Error ? error.message : String(error)}\n`;
}

// Builds once, then rebuilds on every source change until interrupted. A change
// that lands while a build is running queues exactly one more build, so a burst
// of edits collapses into a single rebuild instead of piling up.
async function watch(opts) {
  printReport(await build(opts), opts);
  let running = false;
  let pending = false;
  let stopped = false;
  const rebuild = async () => {
    if (running) {
      pending = true;
      return;
    }
    running = true;
    do {
      pending = false;
      try {
        printReport(await build(opts), opts);
      } catch (error) {
        // A broken intermediate edit must not end the session.
        process.stderr.write(failure(error));
      }
    } while (pending && !stopped);
    running = false;
  };
  const watcher = watchTree(path.resolve(opts.src), () => {
    void rebuild();
  });
  process.stderr.write('watching for changes\n');
  await new Promise((resolve) => {
    const stop = () => {
      stopped = true;
      watcher.close();
      resolve();
    };
    process.once('SIGINT', stop);
    process.once('SIGTERM', stop);
  });
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    process.stdout.write(USAGE);
    return 0;
  }
  if (opts.watch) {
    await watch(opts);
    return 0;
  }
  printReport(await build(opts), opts);
  return 0;
}

main().then(
  (code) => {
    process.exitCode = code;
  },
  (error) => {
    process.stderr.write(failure(error));
    process.exitCode = 1;
  },
);
