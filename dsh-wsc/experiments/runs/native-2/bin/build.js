#!/usr/bin/env node
import { build, parseArgs, USAGE } from '../lib/build.js';
import { startWatch } from '../lib/watch.js';

function printReport(opts, report) {
  if (opts.json) {
    process.stdout.write(`${JSON.stringify(report)}\n`);
    return;
  }
  process.stdout.write(
    `built ${report.built.length}, skipped ${report.skipped.length}, removed ${report.removed.length} in ${report.durationMs}ms\n`,
  );
}

function waitForSignal() {
  return new Promise((resolve) => {
    const stop = () => {
      process.off('SIGINT', stop);
      process.off('SIGTERM', stop);
      resolve();
    };
    process.on('SIGINT', stop);
    process.on('SIGTERM', stop);
  });
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    process.stdout.write(USAGE);
    return 0;
  }
  if (!opts.watch) {
    printReport(opts, await build(opts));
    return 0;
  }
  const watcher = await startWatch(opts, {
    onReport: (report) => printReport(opts, report),
    onError: (error) => {
      process.stderr.write(`build failed: ${error instanceof Error ? error.message : String(error)}\n`);
    },
  });
  await waitForSignal();
  watcher.close();
  return 0;
}

main().then(
  (code) => {
    process.exitCode = code;
  },
  (error) => {
    process.stderr.write(`build failed: ${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  },
);
